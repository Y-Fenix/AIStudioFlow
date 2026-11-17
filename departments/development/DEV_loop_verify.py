"""Real emulator-only Loop touch acceptance; uses visible controls, no injected win."""
import json
import re
import subprocess
import time
from pathlib import Path


def DEV_verify_loop(root, package_name, tools, *, serial, check_cancelled=None):
    root=Path(root)
    adb=Path(tools['sdk'])/'platform-tools/adb'
    def DEV_adb(*args):
        if check_cancelled:check_cancelled()
        result=subprocess.run([str(adb),'-s',serial,*map(str,args)],capture_output=True,timeout=45,check=True)
        return result.stdout
    def DEV_saved_state():
        import xml.etree.ElementTree as ET
        names=DEV_adb('shell','run-as',package_name,'ls','shared_prefs').decode().split()
        for name in names:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.xml',name):continue
            xml=DEV_adb('shell','run-as',package_name,'cat','shared_prefs/'+name)
            tree=ET.fromstring(xml)
            for node in tree:
                if node.get('name')=='state':return json.loads(node.text)
        raise RuntimeError('Loop持久化状态不存在')
    def DEV_confirm_dialog():
        DEV_adb('shell','uiautomator','dump','/sdcard/studioflow-loop-window.xml')
        import xml.etree.ElementTree as ET
        tree=ET.fromstring(DEV_adb('shell','cat','/sdcard/studioflow-loop-window.xml'))
        button=next((n for n in tree.iter('node') if n.get('resource-id','').endswith('button1')),None)
        if button is None:raise RuntimeError('预期的Loop确认框未出现')
        coords=list(map(int,re.findall(r'\d+',button.get('bounds',''))))
        DEV_adb('shell','input','tap',(coords[0]+coords[2])//2,(coords[1]+coords[3])//2)
    DEV_adb('install','--no-incremental','-r',root/'artifacts/game-debug.apk')
    # Fresh package per build; clear only its own app data for deterministic level 1.
    DEV_adb('shell','pm','clear',package_name)
    DEV_adb('logcat','-c')
    component=package_name+'/studioflow.generated.MainActivity'
    DEV_adb('shell','am','start','-W','-n',component)
    time.sleep(.5)
    DEV_confirm_dialog()
    width,height=map(int,re.search(r'(\d+)x(\d+)',DEV_adb('shell','wm','size').decode()).groups())
    # Read actual content bounds; Android navigation bar is outside the custom View.
    DEV_adb('shell','uiautomator','dump','/sdcard/studioflow-loop-window.xml')
    xml=DEV_adb('shell','cat','/sdcard/studioflow-loop-window.xml').decode()
    bounds=re.findall(r'class="android.view.View"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',xml)
    if not bounds:raise RuntimeError('无法读取Loop游戏画布边界')
    left,top,right,bottom=map(int,bounds[-1]);scale=(right-left)/400
    def DEV_tap(x,y):DEV_adb('shell','input','tap',round(left+x*scale),round(top+y*scale))
    canvas_h=(bottom-top)/scale
    (root/'android-ready.png').write_bytes(DEV_adb('exec-out','screencap','-p'))
    oy=max(180,(canvas_h-344)/2-10)
    layout=json.loads(re.search(r'QA_LOOP_FIRST=(\[[^\]]+\])',(root/'build.log').read_text()).group(1))
    first=next(i for i,v in enumerate(layout) if v)
    DEV_tap(28+(first%4+.5)*86,oy+(first//4+.5)*86)
    saved=DEV_saved_state()
    DEV_adb('shell','am','force-stop',package_name)
    DEV_adb('shell','am','start','-W','-n',component)
    if DEV_saved_state()!=saved:raise RuntimeError('Loop当前局盘面或计数恢复不一致')
    restored=DEV_adb('logcat','-d','-s','StudioFlowGame:I').decode(errors='replace')
    if 'LOOP ready level=1 moves=1 hints=0' not in restored:raise RuntimeError('当前局步数恢复失败')
    DEV_tap(110,canvas_h-65)
    DEV_confirm_dialog()
    for _ in range(16):
        DEV_tap(290,canvas_h-65)
        activity=DEV_adb('logcat','-d','-s','StudioFlowGame:I').decode(errors='replace')
        if 'LOOP won level=1' in activity:break
    logs=DEV_adb('logcat','-d','-s','StudioFlowGame:I','AndroidRuntime:E').decode(errors='replace')
    if 'FATAL EXCEPTION' in logs or not all(v in logs for v in ('LOOP turn=','LOOP restart','LOOP won level=1')):
        (root/'android-loop.log').write_text(logs)
        raise RuntimeError('Loop触控/重开/提示胜利证据不完整')
    (root/'android-won.png').write_bytes(DEV_adb('exec-out','screencap','-p'))
    DEV_adb('logcat','-c')
    DEV_tap(200,canvas_h-65)
    transition=DEV_adb('logcat','-d','-s','StudioFlowGame:I').decode(errors='replace')
    if 'LOOP next level=2' not in transition:raise RuntimeError('Loop未进入第2关')
    DEV_adb('shell','am','force-stop',package_name)
    DEV_adb('shell','am','start','-W','-n',component)
    logs=DEV_adb('logcat','-d','-s','StudioFlowGame:I','AndroidRuntime:E').decode(errors='replace')
    (root/'android-loop.log').write_text('Level 1 acceptance:\n'+activity+'\nLevel transition and restart:\n'+logs)
    if not all(v in logs for v in ('LOOP next level=2','LOOP ready level=2')):raise RuntimeError('Loop下一关保存证据不完整')
    state=DEV_saved_state()
    if state['level']!=2 or 1 not in state['completed']:raise RuntimeError('Loop完成集合或当前关卡未保存')
    (root/'android-restored-state.json').write_text(json.dumps(state,indent=2))
    (root/'android-level2.png').write_bytes(DEV_adb('exec-out','screencap','-p'))
    return {'name':'android_loop_touch','passed':True,'evidence':str(root/'android-loop.log'),
            'scope':'API35模拟器真实安装/旋转/重开/可见提示解题/下一关/进程重启盘面与步数及关卡保存；不是无提示人工通关或真机验收'}
