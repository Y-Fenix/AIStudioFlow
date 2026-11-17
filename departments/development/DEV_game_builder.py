"""Build a real offline Android memory game in a fresh isolated directory.

No database access, arbitrary model code execution, existing project edits or Git.
SDK installation/licence acceptance is an operator prerequisite, never automatic.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import zipfile
from xml.sax.saxutils import escape

from departments.development.DEV_game_template import DEV_ACTIVITY, DEV_RULES, DEV_RULES_TEST
from departments.development.DEV_loop_template import DEV_LOOP_ACTIVITY, DEV_LOOP_RULES, DEV_LOOP_TEST

DEV_ANDROID_TEST_LOCK = threading.Lock()


def DEV_normalize_spec(value):
    if isinstance(value, dict) and value.get('game_type') == 'loop':
        return {'game_type':'loop','title':str(value.get('title') or 'Loop Garden')[:40],
                'levels':1000,'content_version':'loop-content-v1','board_sizes':{'1-100':4,'101-400':5,'401-1000':6},
                'pipe_types':['empty','straight','corner'],'hint_counts_as_move':False,
                'save_scope':'current_board_moves_hints_completed_levels','multiple_loops_allowed':True}
    if not isinstance(value, dict) or value.get('game_type') != 'memory_match':
        raise ValueError('当前真实构建仅支持 memory_match（触控记忆配对），不能冒充其他玩法')
    title = str(value.get('title') or 'Memory Garden').strip()[:40]
    color = str(value.get('accent_color', '#54B49B'))
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        color = '#54B49B'
    return {'game_type': 'memory_match', 'title': title,
            'pairs': max(2, min(8, int(value.get('pairs', 6)))),
            'time_limit_seconds': max(30, min(300, int(value.get('time_limit_seconds', 90)))),
            'accent_color': color,
            'adaptation_notes': str(value.get('adaptation_notes', ''))[:2000]}


def DEV_prepare_root(output_root):
    if '..' in Path(output_root).parts:
        raise ValueError('构建目录不得包含路径穿越片段')
    root = Path(os.path.abspath(os.fspath(output_root)))
    for part in [root, *root.parents]:
        if part.is_symlink():
            raise ValueError('构建目录及父目录不得是符号链接')
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError('构建目录必须不存在或为空，禁止覆盖现有工程')
    root.mkdir(parents=True, exist_ok=True)
    return root


def DEV_discover_tools():
    sdk_options = [os.environ.get('STUDIOFLOW_ANDROID_SDK'), os.environ.get('ANDROID_SDK_ROOT'),
                   os.environ.get('ANDROID_HOME'), str(Path.home() / 'Library/Android/sdk'),
                   str(Path.home() / 'Android/Sdk')]
    for option in sdk_options:
        if not option:
            continue
        sdk = Path(option).expanduser()
        builds = sorted((sdk / 'build-tools').glob('*'), key=lambda p: [int(x) for x in re.findall(r'\d+', p.name)], reverse=True)
        platforms = sorted((sdk / 'platforms').glob('android-*/android.jar'), key=lambda p: int(p.parent.name.split('-')[-1]), reverse=True)
        if builds and platforms and all((builds[0] / tool).is_file() for tool in ('aapt2', 'd8', 'zipalign', 'apksigner')):
            java_home = os.environ.get('JAVA_HOME')
            result = {'sdk': str(sdk), 'android_jar': str(platforms[0])}
            for name in ('aapt2', 'd8', 'zipalign', 'apksigner'):
                result[name] = str(builds[0] / name)
            for name in ('javac', 'java', 'keytool'):
                found = str(Path(java_home) / 'bin' / name) if java_home else shutil.which(name)
                if not found or not Path(found).is_file():
                    raise RuntimeError('Android 构建缺少 JDK 工具：' + name)
                result[name] = found
            return result
    raise RuntimeError('缺少完整Android SDK；请配置STUDIOFLOW_ANDROID_SDK并安装platforms;android-35和build-tools;35.0.0。未生成APK。')


def DEV_run(command, root, log, *, check_cancelled=None, timeout=180):
    if check_cancelled:
        check_cancelled()
    with log.open('ab') as output:
        output.write(('\n$ ' + ' '.join(str(arg) for arg in command) + '\n').encode())
        output.flush()
        process = subprocess.Popen([str(arg) for arg in command], cwd=root, stdout=output, stderr=subprocess.STDOUT)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if check_cancelled:
                    check_cancelled()
                if time.monotonic() - started > timeout:
                    raise TimeoutError('构建步骤超时：' + Path(str(command[0])).name)
                time.sleep(.1)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        if process.returncode:
            raise RuntimeError(f'构建步骤失败：{Path(str(command[0])).name}，退出码{process.returncode}；日志：{log}')


def DEV_verify_android(root, package_name, tools, spec, *, serial, check_cancelled=None):
    """Explicit emulator-only UI smoke; never installs on a real phone."""
    if not re.fullmatch(r'emulator-\d+', serial):
        raise ValueError('自动运行验收仅允许明确指定的Android模拟器serial')
    while not DEV_ANDROID_TEST_LOCK.acquire(timeout=.2):
        if check_cancelled:
            check_cancelled()
    try:
        return DEV_verify_android_locked(root, package_name, tools, spec, serial=serial, check_cancelled=check_cancelled)
    finally:
        DEV_ANDROID_TEST_LOCK.release()


def DEV_verify_android_locked(root, package_name, tools, spec, *, serial, check_cancelled=None):
    root = Path(root)
    if spec['game_type'] == 'loop':
        from departments.development.DEV_loop_verify import DEV_verify_loop
        return DEV_verify_loop(root, package_name, tools, serial=serial, check_cancelled=check_cancelled)
    adb = Path(tools['sdk']) / 'platform-tools/adb'
    log = root / 'android-smoke.log'
    def DEV_adb(*arguments):
        if check_cancelled:
            check_cancelled()
        result = subprocess.run([str(adb), '-s', serial, *map(str, arguments)], capture_output=True, timeout=45)
        with log.open('ab') as stream:
            stream.write(('$ adb ' + ' '.join(map(str, arguments)) + '\n').encode() + result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('Android模拟器验收命令失败：' + str(arguments[0]) + '；见' + str(log))
        return result.stdout
    def DEV_wait_for(marker, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            output = DEV_adb('logcat', '-d', '-s', 'StudioFlowGame:I', 'AndroidRuntime:E').decode(errors='replace')
            if 'FATAL EXCEPTION' in output:
                raise RuntimeError('Android应用崩溃；见' + str(log))
            if marker in output:
                return
            time.sleep(.2)
        raise RuntimeError('Android运行证据未出现：' + marker + '；见' + str(log))
    DEV_adb('install', '--no-incremental', '-r', root / 'artifacts/game-debug.apk')
    size = DEV_adb('shell', 'wm', 'size').decode()
    match = re.search(r'(\d+)x(\d+)', size)
    if not match:
        raise RuntimeError('无法读取模拟器尺寸')
    width, height = map(int, match.groups())
    def DEV_tap(x, y):
        DEV_adb('shell', 'input', 'tap', round(width*x), round(height*y))
    component = package_name + '/studioflow.generated.MainActivity'
    DEV_adb('logcat', '-c')
    DEV_adb('shell', 'am', 'force-stop', package_name)
    DEV_adb('shell', 'am', 'start', '-W', '-n', component, '--el', 'qa_seed', '42', '--ei', 'qa_seconds', '2')
    DEV_wait_for('STATE ready')
    (root / 'android-ready.png').write_bytes(DEV_adb('exec-out', 'screencap', '-p'))
    DEV_tap(.5, .875)
    DEV_wait_for('STATE playing')
    DEV_tap(.16, .34)
    DEV_wait_for('TAP index=0')
    DEV_wait_for('STATE lost', timeout=8)
    (root / 'android-lost.png').write_bytes(DEV_adb('exec-out', 'screencap', '-p'))
    DEV_adb('logcat', '-c')
    DEV_tap(.5, .875)
    DEV_wait_for('STATE playing')
    DEV_adb('shell', 'am', 'force-stop', package_name)
    DEV_adb('logcat', '-c')
    DEV_adb('shell', 'am', 'start', '-W', '-n', component, '--el', 'qa_seed', '42', '--ei', 'qa_seconds', '90')
    DEV_wait_for('STATE ready')
    DEV_tap(.5, .875)
    DEV_wait_for('STATE playing')
    deck_match = re.search(r'QA_DECK=(\[[\d, ]+\])', (root / 'build.log').read_text())
    if not deck_match:
        raise RuntimeError('缺少JVM确定性牌组证据')
    deck = json.loads(deck_match.group(1))
    gap = .025
    cw = (.88-gap*3)/4
    ch = min(height*.115, width*cw*1.12)/height
    for value in range(spec['pairs']):
        for index in [i for i, card in enumerate(deck) if card == value]:
            DEV_tap(.06+(index%4)*(cw+gap)+cw/2, .29+(index//4)*(ch+width*gap/height)+ch/2)
    DEV_wait_for('STATE won')
    (root / 'android-won.png').write_bytes(DEV_adb('exec-out', 'screencap', '-p'))
    return {'name': 'android_emulator_touch_smoke', 'passed': True, 'evidence': str(log),
            'scope': '真实模拟器安装、冷启动、开始、触控、2秒QA时钟失败、重开、确定性牌组逐张触控胜利；非真机验收', 'serial': serial}


def DEV_build_game(output_root, brief, *, progress=None, check_cancelled=None, model=None):
    if check_cancelled:
        check_cancelled()
    if not brief or not str(brief).strip():
        raise ValueError('需要非空游戏需求')
    root = DEV_prepare_root(output_root)
    log = root / 'build.log'
    def DEV_emit(stage):
        if check_cancelled:
            check_cancelled()
        if progress:
            progress({'stage': stage, 'message': stage, 'log_path': str(log)})
    try:
        DEV_emit('检查Android工具链')
        tools = DEV_discover_tools()
        DEV_emit('提取受控离线游戏规格')
        if model is not None:
            data = model.request_json('将以下已提供的游戏生产资料转成受控Android原型规格。只能生成JSON数据，不能生成代码或命令。'
                                      '构建器支持loop（点击旋转管线、闭合全部连接、过关）和memory_match（记忆配对）。根据需求选对应类型。'
                                      '若不是这两种玩法，game_type填unsupported，不能偷换玩法。'
                                      '返回{game_type,title,pairs:2到8,time_limit_seconds:30到300,accent_color:"#54B49B",adaptation_notes}。'
                                      'title应简短；adaptation_notes明确原需求哪些未实现。资料：\n' + str(brief)[:100000])
        elif isinstance(brief, dict):
            data = brief
        elif 'loop' in str(brief).lower():
            data = {'game_type': 'loop'}
        elif any(word in str(brief).lower() for word in ('memory', '记忆', '配对')):
            data = {'game_type': 'memory_match'}
        else:
            raise ValueError('无模型时须传入memory_match结构化规格或明确记忆配对需求')
        spec = DEV_normalize_spec(data)
        (root / 'game-spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
        for directory in ('src/studioflow/generated', 'test/studioflow/generated', 'classes', 'test-classes', 'assets', 'dex', 'artifacts'):
            (root / directory).mkdir(parents=True, exist_ok=True)
        (root / 'assets/game-spec.json').write_text(json.dumps(spec, ensure_ascii=False))
        source = root / 'src/studioflow/generated'
        loop = spec['game_type'] == 'loop'
        (source / 'GameRules.java').write_text(DEV_LOOP_RULES if loop else DEV_RULES)
        (source / 'MainActivity.java').write_text(DEV_LOOP_ACTIVITY if loop else DEV_ACTIVITY)
        test = root / 'test/studioflow/generated/GameRulesTest.java'
        test.write_text(DEV_LOOP_TEST if loop else DEV_RULES_TEST)
        package_name = 'studioflow.game.r' + hashlib.sha256(str(root).encode()).hexdigest()[:12]
        manifest = ('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="' + package_name + '">'
                    '<uses-sdk android:minSdkVersion="23" android:targetSdkVersion="35"/>'
                    '<application android:label="' + escape(spec['title'], {'"': '&quot;'}) + '" android:theme="@android:style/Theme.Material.NoActionBar" android:debuggable="true" android:allowBackup="false" android:supportsRtl="true">'
                    '<activity android:name="studioflow.generated.MainActivity" android:screenOrientation="portrait" android:exported="true">'
                    '<intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter>'
                    '</activity></application></manifest>')
        (root / 'AndroidManifest.xml').write_text(manifest)
        def DEV_exec(args):
            DEV_run(args, root, log, check_cancelled=check_cancelled)
        DEV_emit('执行真实Java玩法测试')
        DEV_exec([tools['javac'], '-encoding', 'UTF-8', '-d', root / 'test-classes', source / 'GameRules.java', test])
        DEV_exec([tools['java'], '-cp', root / 'test-classes', 'studioflow.generated.GameRulesTest', str(spec.get('pairs',0)), str(root / 'level-validation.json')])
        checks = [{'name': 'game_rules_jvm', 'passed': True, 'evidence': str(log),
                   'scope': ('真实JVM执行：1000关旋转、可解性及提示测试；不代表Android UI实测' if loop else '真实JVM执行：洗牌、无效触控、重复触控、错配锁定、配对、胜利、重开；不代表Android UI实测')}]
        DEV_emit('编译Android源码与DEX')
        DEV_exec([tools['javac'], '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-bootclasspath', tools['android_jar'], '-d', root / 'classes', *sorted(source.glob('*.java'))])
        DEV_exec([tools['d8'], '--lib', tools['android_jar'], '--min-api', '23', '--output', root / 'dex', *sorted((root / 'classes').rglob('*.class'))])
        DEV_emit('打包并生成本次独立debug签名')
        DEV_exec([tools['aapt2'], 'link', '-o', root / 'unsigned.apk', '-I', tools['android_jar'], '--manifest', root / 'AndroidManifest.xml', '-A', root / 'assets'])
        with zipfile.ZipFile(root / 'unsigned.apk', 'a', zipfile.ZIP_DEFLATED) as archive:
            archive.write(root / 'dex/classes.dex', 'classes.dex')
        DEV_exec([tools['zipalign'], '-f', '4', root / 'unsigned.apk', root / 'aligned.apk'])
        # Public debug-only password. The disposable key is never returned as an artifact.
        DEV_exec([tools['keytool'], '-genkeypair', '-keystore', root / 'debug.keystore', '-storepass', 'android', '-keypass', 'android', '-alias', 'androiddebugkey', '-dname', 'CN=StudioFlow Debug', '-keyalg', 'RSA', '-validity', '365'])
        apk = root / 'artifacts/game-debug.apk'
        DEV_exec([tools['apksigner'], 'sign', '--ks', root / 'debug.keystore', '--ks-pass', 'pass:android', '--out', apk, root / 'aligned.apk'])
        (root / 'debug.keystore').chmod(0o600)
        DEV_exec([tools['apksigner'], 'verify', '--verbose', apk])
        DEV_exec([tools['aapt2'], 'dump', 'badging', apk])
        checks.append({'name': 'android_apk_signature_and_manifest', 'passed': True, 'evidence': str(log), 'scope': '真实Android编译、DEX、APK签名和manifest校验；尚未安装/启动'})
        with zipfile.ZipFile(apk) as archive:
            if not {'classes.dex', 'AndroidManifest.xml', 'assets/game-spec.json'}.issubset(archive.namelist()):
                raise RuntimeError('APK结构缺少必要文件')
        android_serial = os.environ.get('STUDIOFLOW_ANDROID_TEST_SERIAL', '')
        if android_serial:
            DEV_emit('执行Android模拟器触控与胜负验收')
            checks.append(DEV_verify_android(root, package_name, tools, spec, serial=android_serial, check_cancelled=check_cancelled))
        (root / 'verification.json').write_text(json.dumps({'checks': checks, 'tools': tools}, ensure_ascii=False, indent=2))
        (root / 'README.md').write_text(('Loop Garden：点击旋转管线，闭合全部连接；提示、重开、关卡推进及进度保存。\n' if loop else '真实Android离线记忆配对原型。仅支持memory_match。') + ('\n旋转→闭环→下一关。' if loop else '\n开始→两张触控配对→限时胜利/失败→重开。') + '无广告/IAP/联网/正式签名。\n安装：adb install artifacts/game-debug.apk\n启动：adb shell am start -n ' + package_name + '/studioflow.generated.MainActivity\n玩法测试：java -cp test-classes studioflow.generated.GameRulesTest\n重建（在StudioFlow仓库）：python3 tools/DEV_build_android_game.py --spec <本工程game-spec.json绝对路径> --output <新的空目录>\nQA时钟/固定牌组仅用于本debug原型验收，尚非发布包。\n')
        source_zip = root / 'artifacts/game-source.zip'
        with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
            for pattern in ('src/**/*.java', 'test/**/*.java', 'assets/*', 'README.md', 'AndroidManifest.xml', 'game-spec.json'):
                for path in sorted(root.glob(pattern)):
                    archive.write(path, path.relative_to(root))
        artifacts = []
        for path, kind in ((apk, 'android_apk'), (source_zip, 'source_archive'), (root / 'game-spec.json', 'game_spec'), (root / 'build.log', 'build_log'), (root / 'verification.json', 'verification')):
            artifacts.append({'path': str(path), 'name': path.name, 'kind': kind, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size_bytes': path.stat().st_size})
        if loop:
            path=root/'level-validation.json'
            artifacts.append({'path':str(path),'name':path.name,'kind':'level_validation','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size_bytes':path.stat().st_size})
        for path in sorted(root.glob('android-*')):
            artifacts.append({'path': str(path), 'name': path.name, 'kind': 'screenshot' if path.suffix == '.png' else 'runtime_log', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size_bytes': path.stat().st_size})
        DEV_emit('APK与模拟器验收完成，等待人工审核' if android_serial else 'APK构建完成，等待Android运行验收')
        return {'artifacts': artifacts, 'checks': checks, 'gaps': ['尚未在真实手机验收' if android_serial else '尚未在Android设备执行安装与触控验收；JVM规则测试不代表UI质量通过', '受控离线loop/记忆配对模板；不含任意玩法生成、广告、IAP、正式发行签名'],
                'project_path': str(root), 'package_name': package_name, 'spec': spec}
    except BaseException as error:
        (root / 'failure.json').write_text(json.dumps({'error_type': type(error).__name__, 'message': str(error), 'log_path': str(log)}, ensure_ascii=False, indent=2))
        raise
