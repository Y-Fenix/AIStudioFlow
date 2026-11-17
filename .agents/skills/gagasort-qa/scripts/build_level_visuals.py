#!/usr/bin/env python3
"""离线复用生产 WaterPipe 网格数学；不启动 Editor，不验证实际 GPU 画面。

依赖 build_level_splines.py 生成的程序集。仅在临时副本移除场景装配方法，
用托管 Mesh 收集原始生产顶点/索引；所有采样、岸壁和三角形算法保持原样。
"""
import argparse,difflib,hashlib,json,re,subprocess,sys,tempfile
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def span(s,signature):
 start=s.index(signature);b=s.index('{',start);d=1;i=b+1
 while d:
  if s[i]=='{':d+=1
  elif s[i]=='}':d-=1
  i+=1
 return start,i
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 for n in ['repo','build-dir','input','output','spline-build']:ap.add_argument('--'+n,type=Path,required=True)
 ap.add_argument('--radius',type=float,required=True);a=ap.parse_args()
 repo=a.repo.resolve();out=a.build_dir.resolve();out.mkdir(parents=True,exist_ok=True)
 kernel=a.spline_build.resolve();km=json.loads((kernel/'manifest.json').read_text());runtime=Path(km['runtime']);unity=runtime.parents[3];dotnet=unity/'NetCoreRuntime/dotnet';csc=unity/'DotNetSdkRoslyn/csc.dll'
 if Path(km['repo']).resolve()!=repo:raise RuntimeError('spline kernel 来自其它仓库')
 if km['packages_lock_sha256']!=sha(repo/'GagaSort/Packages/packages-lock.json'):raise RuntimeError('spline kernel 包版本已过期，请重建')
 if km['radius']!=a.radius:raise RuntimeError('spline kernel 半径与本次不一致')
 stale=[x['path'] for x in km['sources'] if not Path(x['path']).is_file() or sha(Path(x['path']))!=x['sha256']]
 if stale:raise RuntimeError('spline kernel 源码已变化，请重建：'+str(stale))
 base=repo/'GagaSort/Assets/Scripts/GamePlay/GagaSort/Runtime';scripts=Path(__file__).resolve().parent
 manifest={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'input_sha256':sha(a.input),'kernel_manifest_sha256':sha(kernel/'manifest.json'),'sources':[],'boundaries':['生产网格数学原样；移除未调用的场景装配方法，以托管Mesh收集生产顶点/三角形。','单位格、Prefab单位变换；不同高程仅记录，不以XY投影相交判定3D缺陷。','检查水面中央实体带翻面与非邻接墙顶正面积相交风险，不代表GPU画面或玩家Bug确认。','配方解码复用生产私有DecodeSamples；校验几何指纹及同目录分组bytes头的数据库指纹和关号，不重新计算数据库内容指纹，不验证Resources/Hotfix实际运行选源。']}
 def track(p):manifest['sources'].append({'path':str(p),'sha256':sha(p)})
 track(Path(__file__).resolve());track(a.input.resolve());track(repo/'GagaSort/Packages/packages-lock.json')
 manifest['kernel_verified_sources']=len(km['sources'])
 manifest['kernel_assemblies']=[{'path':str(kernel/n),'sha256':sha(kernel/n)} for n in ['Unity.Mathematics.dll','Unity.Splines.dll','GagaSort.Geometry.dll']]
 def patched(path,text,name):
  track(path);original=path.read_text();target=out/name;target.write_text(text)
  (out/(name+'.diff')).write_text(''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile=str(path),tofile=str(target))))
  return target
 path=base/'View/WaterPipe/WaterPipeMeshBuilder.cs';s=path.read_text()
 for sig in ['public GameObject Build(IReadOnlyList<Vector3>','internal GameObject Build(WaterPipeSharedMeshData','private void CreatePipeShadow(','private void CreateChannelShell(','private void CreateWaterSurface(','private void CreateGdCausticsSurface(','private void AddMesh(','private static GameObject CreateChild(']:
  st,en=span(s,sig);s=s[:st]+s[en:]
 s=s.replace('using UnityEngine.Rendering;','using UnityEngine.Rendering;\nusing Mesh = GagaSort.ProbeMesh;')
 sources=[patched(path,s,'WaterPipeMeshBuilder.Headless.cs')]
 rp=base/'View/WaterPipe/WaterPipeRenderer.cs';rs=rp.read_text();st,en=span(rs,'internal sealed class WaterPipeBuildSettings');settings='using UnityEngine;\nnamespace GagaSort {\n'+rs[st:en]+'\n}\n';sources.append(patched(rp,settings,'WaterPipeBuildSettings.Extracted.cs'))
 helper=scripts/'level_spline_probe.cs';hs=helper.read_text();hs=hs[:hs.index(' static void Main(')]+'}\n';hs=hs.replace('class GeometryProbe','class GeometryInput').replace(' static GagaSortLevelData Parse(',' public static GagaSortLevelData Parse(');sources.append(patched(helper,hs,'GeometryInput.Extracted.cs'))
 sources += [base/'Data/GagaSortBoardData.cs',base/'View/WaterPipe/GagaSortWaterPipePathUtility.cs',base/'View/WaterPipe/WaterPipeRecipeLibrary.cs',scripts/'level_visual_probe.cs']
 for p in sources:
  if p.parent!=out:track(p)
 prefab=repo/'GagaSort/Assets/Art/Effect/Prefab/GagaSort/WaterPipe/WaterPipe.prefab';track(prefab);pt=prefab.read_text()
 names=re.findall(r'public (?:float|int) (\w+);',settings);values={}
 for name in names:
  source=name+'Cells' if re.search(r'^  '+name+r'Cells:',pt,re.M) else name
  m=re.search(r'^  '+source+r': ([-.\d]+)$',pt,re.M)
  if m:values[name]=float(m[1])
 values['CornerJoinSegments']=int(values['CornerJoinSegments'])
 values['WallEdgeHeight']=values['WallHeight']
 offset=re.search(r'^  PipeShadowOffsetCells: \{x: ([-.\d]+), y: ([-.\d]+)\}$',pt,re.M)
 if not offset:raise RuntimeError('正式 Prefab 缺少 PipeShadowOffsetCells')
 values['PipeShadowOffset']=[float(offset[1]),float(offset[2])]
 recipes=[]
 try:import msgpack
 except ImportError:
  for dependency_dir in [Path('/tmp/gagasort-qa-layout-deps'),Path(tempfile.gettempdir())/'gagasort-qa-layout-deps']:
   if dependency_dir.is_dir():sys.path.insert(0,str(dependency_dir))
  import msgpack
 # 正式资产在.gitignore覆盖目录中，Path.rglob仍必须枚举。
 for p in sorted((repo/'GagaSort/Assets').rglob('*RecipeLibrary*main_group_*.asset')):
  if '/default/' not in str(p):continue
  txt=p.read_text();entries=[]
  for m in re.finditer(r'  - Mode: (\d+)\n    LevelId: (\d+)\n    SampleCount: (\d+)\n    Data: ([0-9a-fA-F]+)',txt):
   entries.append({'mode':int(m[1]),'number':int(m[2]),'count':int(m[3]),'hex':m[4]})
  if entries:
   database=p.with_name(p.stem.replace('GagaSortWaterPipeRecipeLibrary_','gagasort_levels_')+'.bytes');track(database)
   db=msgpack.unpackb(database.read_bytes(),strict_map_key=False)
   track(p);recipes.append({'path':str(p),'sha256':sha(p),'geometry_fingerprint':re.search(r'  GeometryFingerprint: (.+)',txt)[1],'database_fingerprint':re.search(r'  DatabaseFingerprint: (.+)',txt)[1],'database_path':str(database),'expected_database_fingerprint':db[3],'database_entries':{str(mode):list(levels) for mode,levels in db[2].items()},'entries':entries})
 payload={'settings':values,'recipes':recipes};payload_path=out/'visual-input.json';payload_path.write_text(json.dumps(payload))
 refs=['-r:'+str(p) for p in sorted(runtime.glob('*.dll'))]+['-r:'+str(p) for p in sorted((unity/'Managed/UnityEngine').glob('*.dll'))]+['-r:'+str(kernel/n) for n in ['Unity.Mathematics.dll','Unity.Splines.dll','GagaSort.Geometry.dll']]
 rsp=out/'VisualProbe.rsp';rsp.write_text('\n'.join('"'+x+'"' for x in ['-nologo','-target:exe','-langversion:latest','-out:'+str(out/'VisualProbe.dll')]+refs+list(map(str,sources))))
 r=subprocess.run([str(dotnet),str(csc),'@'+str(rsp)],cwd=repo,text=True,capture_output=True);(out/'compile.log').write_text(r.stdout+r.stderr)
 if r.returncode:raise RuntimeError(r.stdout+r.stderr)
 (out/'VisualProbe.runtimeconfig.json').write_text(json.dumps({'runtimeOptions':{'tfm':'net6.0','framework':{'name':'Microsoft.NETCore.App','version':runtime.name}}}))
 for p in list(kernel.glob('*.dll')):
  target=out/p.name
  if target.exists() and target.resolve()!=p.resolve():raise RuntimeError('build-dir 中存在其它 kernel 程序集：'+str(target))
  if not target.exists():target.symlink_to(p.resolve())
 a.output.resolve().parent.mkdir(parents=True,exist_ok=True)
 r=subprocess.run([str(dotnet),str(out/'VisualProbe.dll'),str(a.input.resolve()),str(payload_path),str(a.output.resolve()),str(a.radius)],cwd=repo,text=True,capture_output=True);(out/'run.log').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr)
 manifest['head_after']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip();manifest['sources_changed']=[x['path'] for x in manifest['sources'] if sha(Path(x['path']))!=x['sha256']]
 manifest['kernel_sources_changed']=[x['path'] for x in km['sources'] if not Path(x['path']).is_file() or sha(Path(x['path']))!=x['sha256']]
 manifest['kernel_assemblies_changed']=[x['path'] for x in manifest['kernel_assemblies'] if sha(Path(x['path']))!=x['sha256']]
 if a.output.exists():manifest['output_sha256']=sha(a.output)
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 if r.returncode or manifest['sources_changed'] or manifest['kernel_sources_changed'] or manifest['kernel_assemblies_changed']:raise RuntimeError('执行失败或源码变化，见run.log/manifest.json')
if __name__=='__main__':main()
