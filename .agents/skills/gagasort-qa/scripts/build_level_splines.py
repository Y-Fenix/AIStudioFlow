#!/usr/bin/env python3
"""复用生产路径/关联布局的离线探针；不是 Unity Editor 或 Player 验证。

编译产物仅写 --build-dir，结果写 --output。使用 packages-lock 实际版本和官方 packages.unity.com
包；仅将 CurveUtility 数组弧长重载改用该官方包 NativeArray 重载的同一循环，
隔离 native allocator；不替代曲线数学、不定义 UNITY_EDITOR、不编译 SplineJobs。
"""
from pathlib import Path
import argparse,difflib,hashlib,json,subprocess,tarfile,urllib.request

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser(description=__doc__)
 a.add_argument('--repo',type=Path,required=True);a.add_argument('--build-dir',type=Path,required=True)
 a.add_argument('--input',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
 a.add_argument('--radius',type=float,required=True);a.add_argument('--unity',type=Path)
 opt=a.parse_args();repo=opt.repo.resolve();root=opt.build_dir.resolve();root.mkdir(parents=True,exist_ok=True)
 project=repo/'GagaSort';lock=project/'Packages/packages-lock.json';versions=json.loads(lock.read_text())['dependencies']
 if opt.unity:unity=opt.unity.resolve()
 else:
  version=(project/'ProjectSettings/ProjectVersion.txt').read_text().splitlines()[0].split(':',1)[1].strip()
  unity=Path('/Applications/Unity/Hub/Editor')/version/'Unity.app/Contents'
 runtime=unity/'NetCoreRuntime/shared/Microsoft.NETCore.App'
 runtimes=sorted(runtime.glob('6.*'),key=lambda x:tuple(map(int,x.name.split('.'))))
 if not runtimes:raise RuntimeError('Unity .NET6 runtime 不存在：'+str(runtime))
 runtime=runtimes[-1];dotnet=unity/'NetCoreRuntime/dotnet';csc=unity/'DotNetSdkRoslyn/csc.dll'
 refs=['-r:'+str(p) for p in sorted(runtime.glob('*.dll'))]+['-r:'+str(p) for p in sorted((unity/'Managed/UnityEngine').glob('*.dll'))]
 manifest={'repo':str(repo),'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'packages_lock_sha256':digest(lock),'input':str(opt.input.resolve()),'input_sha256':digest(opt.input),'radius':opt.radius,'runtime':str(runtime),'packages':{},'sources':[],'boundaries':['未定义 UNITY_EDITOR，未启动或调用 Unity Editor/Player。','排除 SplineJobs.cs，不验证 Jobs/Burst。','仅 CurveUtility.CalculateCurveLengths 数组重载使用同包 NativeArray 重载原始循环以隔离 native allocator。','JSON DTO 人工逐字段映射几何相关字段，不替代正式关卡序列化或完整 Validator。']}
 package_dirs={}
 for name in ['com.unity.mathematics','com.unity.splines']:
  v=versions[name]['version'];archive=root/(name+'-'+v+'.tgz');url='https://packages.unity.com/'+name+'/-/'+name+'-'+v+'.tgz'
  if not archive.exists():
   partial=archive.with_suffix('.partial')
   with urllib.request.urlopen(url,timeout=60) as response,partial.open('wb') as target:
    while chunk:=response.read(1024*1024):target.write(chunk)
   partial.replace(archive)
  dest=root/(name+'-'+v)
  if not (dest/'package/package.json').exists():
   dest.mkdir(exist_ok=True)
   with tarfile.open(archive) as tar:
    for member in tar.getmembers():
     candidate=(dest/member.name).resolve()
     if not candidate.is_relative_to(dest):raise RuntimeError('不安全的归档路径')
     if member.issym() or member.islnk():raise RuntimeError('归档包含链接，停止')
    tar.extractall(dest,filter='data')
  package_dirs[name]=dest/'package';manifest['packages'][name]={'version':v,'url':url,'archive_sha256':digest(archive)}
 def compile(name,sources,extra=(),exe=False):
  args=['-nologo','-target:'+('exe' if exe else 'library'),'-unsafe','-langversion:latest','-out:'+str(root/(name+'.dll'))]+refs+list(extra)+list(map(str,sources))
  rsp=root/(name+'.rsp');rsp.write_text('\n'.join('"'+s+'"' for s in args)+'\n')
  result=subprocess.run([str(dotnet),str(csc),'@'+str(rsp)],cwd=repo,text=True,capture_output=True)
  (root/(name+'-compile.log')).write_text(result.stdout+result.stderr)
  if result.returncode:raise RuntimeError(name+' 编译失败：'+result.stdout+result.stderr)
  for path in sources:manifest['sources'].append({'path':str(path),'sha256':digest(path)})
  print('compiled '+name,flush=True)
 compile('Unity.Mathematics',sorted((package_dirs['com.unity.mathematics']/'Unity.Mathematics').rglob('*.cs')))
 curve_path=package_dirs['com.unity.splines']/'Runtime/CurveUtility.cs';curve=curve_path.read_text()
 # 查找固定签名并用平衡花括号截取，保留官方函数体。
 def body(text,signature):
  begin=text.index('{',text.index(signature));depth=1;i=begin+1
  while depth:
   if text[i]=='{':depth+=1
   elif text[i]=='}':depth-=1
   i+=1
  return begin+1,i-1
 n0,n1=body(curve,'public static void CalculateCurveLengths(BezierCurve curve, NativeArray<DistanceToInterpolation> lookupTable)')
 a0,a1=body(curve,'public static void CalculateCurveLengths(BezierCurve curve, DistanceToInterpolation[] lookupTable)')
 patched=curve[:a0]+curve[n0:n1]+curve[a1:]
 curve_temp=root/'CurveUtility.Headless.cs';curve_temp.write_text(patched)
 (root/'curve-native-array-adaptation.diff').write_text(''.join(difflib.unified_diff(curve.splitlines(True),patched.splitlines(True),fromfile=str(curve_path),tofile=str(curve_temp))))
 sources=[curve_temp if p.name=='CurveUtility.cs' else p for p in sorted((package_dirs['com.unity.splines']/'Runtime').rglob('*.cs')) if p.name!='SplineJobs.cs']
 compile('Unity.Splines',sources,['-r:'+str(root/'Unity.Mathematics.dll')])
 base=project/'Assets/Scripts/GamePlay/GagaSort/Runtime'
 sources=[base/p for p in ['Data/GagaSortEnums.cs','Data/GagaSortGridGeometry.cs','Level/GagaSortLevelData.cs','Level/GagaSortPathBuilder.cs','Logic/GagaSortPoolGeometry.cs','Logic/GagaSortGridGeometryUtility.cs','Config/GagaSortPresentationConfig.cs']]
 sources+=[project/'Assets/Scripts/GamePlay/Gameplay/Contracts/LevelMode.cs']
 sources+=sorted((project/'Assets/Plugins/3rd/NaughtyAttributes/Scripts/Core').rglob('*.cs'))
 annotations=next((project/'Assets/Packages').glob('MessagePack.Annotations.*/lib/netstandard2.0/MessagePack.Annotations.dll'))
 compile('GagaSort.Geometry',sources,['-r:'+str(root/'Unity.Mathematics.dll'),'-r:'+str(root/'Unity.Splines.dll'),'-r:'+str(annotations)])
 probe=Path(__file__).with_name('level_spline_probe.cs')
 if not probe.exists():raise RuntimeError('脚本旁缺少 level_spline_probe.cs')
 compile('GeometryProbe',[probe],['-r:'+str(root/n) for n in ['Unity.Mathematics.dll','Unity.Splines.dll','GagaSort.Geometry.dll']],True)
 (root/'GeometryProbe.runtimeconfig.json').write_text(json.dumps({'runtimeOptions':{'tfm':'net6.0','framework':{'name':'Microsoft.NETCore.App','version':runtime.name}}}))
 for source in list((unity/'Managed/UnityEngine').glob('*.dll'))+[annotations]:
  target=root/source.name
  if not target.exists():target.symlink_to(source)
 for label,args in [('smoke',[]),('geometry',[str(opt.input.resolve()),str(opt.output.resolve()),str(opt.radius)])]:
  result=subprocess.run([str(dotnet),str(root/'GeometryProbe.dll')]+args,cwd=repo,text=True,capture_output=True)
  (root/(label+'-run.log')).write_text(result.stdout+result.stderr);print(result.stdout+result.stderr,flush=True)
  if result.returncode:raise RuntimeError(label+' 运行失败')
 manifest['sources_changed_during_run']=[item['path'] for item in manifest['sources'] if digest(Path(item['path']))!=item['sha256']]
 manifest['output']=str(opt.output.resolve());manifest['output_sha256']=digest(opt.output)
 manifest['head_after']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
 (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 print('manifest='+str(root/'manifest.json'))
 if manifest['sources_changed_during_run']:raise RuntimeError('生产源码在执行中变化：'+str(manifest['sources_changed_during_run']))
if __name__=='__main__':main()
