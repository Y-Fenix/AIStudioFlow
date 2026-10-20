#!/usr/bin/env python3
"""编译平台桥接源码，引用本机Unity程序集；不启动Unity，不写游戏项目。"""
from pathlib import Path
from xml.sax.saxutils import escape
import json,os,subprocess,tempfile,hashlib
root=Path(__file__).resolve().parents[1]
managed=Path('/Applications/Unity/Hub/Editor/2022.3.62f2c1/Unity.app/Contents/Managed')
source=root/'integrations/unity/TestFlowEditorBridge.cs'
refs=[managed/'UnityEngine/UnityEditor.CoreModule.dll',managed/'UnityEngine/UnityEngine.CoreModule.dll',
      managed/'UnityEngine/UnityEngine.JSONSerializeModule.dll']
if not all(p.is_file() for p in refs):raise SystemExit('本机Unity2022.3程序集缺失')
with tempfile.TemporaryDirectory(prefix='testflow-unity-compile-') as folder:
 p=Path(folder)
 project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net9.0</TargetFramework><DefineConstants>UNITY_EDITOR</DefineConstants><EnableDefaultCompileItems>false</EnableDefaultCompileItems><UseSharedCompilation>false</UseSharedCompilation></PropertyGroup><ItemGroup><Compile Include="'+escape(str(source))+'"/>'
 for ref in refs:project+='<Reference Include="'+ref.stem+'"><HintPath>'+escape(str(ref))+'</HintPath></Reference>'
 project+='</ItemGroup></Project>'
 (p/'Bridge.csproj').write_text(project)
 result=subprocess.run([str(root/'.runtimes/dotnet/dotnet'),'build',str(p/'Bridge.csproj'),'--verbosity','quiet'],capture_output=True,text=True,timeout=120,env=dict(os.environ,MSBUILDDISABLENODEREUSE='1',DOTNET_CLI_USE_MSBUILD_SERVER='0'))
 evidence={'scope':'真实Unity程序集类型/语法编译；不是Unity Editor导入或运行验证','returncode':result.returncode,
           'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'references':[str(p) for p in refs],
           'log':result.stdout+result.stderr}
 (root/'data/unity-bridge-compilation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
 print(evidence['log'])
 raise SystemExit(result.returncode)
