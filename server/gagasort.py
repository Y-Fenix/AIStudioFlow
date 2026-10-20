"""GagaSort 本地绑定检查；只读取代码，不切分支、不启动 Unity。"""
import hashlib
import subprocess
from server.processes import run as run_process
import json
import sys
import uuid
from pathlib import Path
from server.execution import normalize_report


def inspect_project(path, branch):
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError('需要本地项目绝对路径')
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError('需要指定目标分支')
    root = Path(path).resolve()
    def git(*args):
        result = run_process(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise ValueError('本地 Git 项目检查失败')
        return result.stdout.strip()
    top = Path(git('rev-parse', '--show-toplevel')).resolve()
    actual = git('symbolic-ref', '--short', 'HEAD')
    if actual != branch.strip():
        raise ValueError('当前分支与指定分支不一致；平台不会自动切换分支')
    project = top / 'GagaSort'
    version_path = project / 'ProjectSettings/ProjectVersion.txt'
    runner = project / 'Assets/Editor/Tools/TEST/TEST_test-business-automation.py'
    if not version_path.is_file():
        raise ValueError('未找到 GagaSort Unity 项目版本文件')
    version = next((line.split(':', 1)[1].strip() for line in version_path.read_text().splitlines()
                    if line.startswith('m_EditorVersion:')), None)
    digest = hashlib.sha256()
    count = 0
    worktree_status = git('status', '--porcelain=v1', '--untracked-files=all')
    submodule_versions = git('submodule', 'status', '--recursive')
    digest.update(worktree_status.encode())
    digest.update(submodule_versions.encode())
    # 包含工作区未提交和未跟踪源码；不读取用户级认证或会话文件。
    for folder in ('Assets', 'Packages', 'ProjectSettings'):
        for file in sorted((project / folder).rglob('*')):
            if file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(project.resolve()) and file.suffix.lower() in ('.cs', '.py', '.json', '.asmdef', '.asmref', '.csv', '.txt', '.asset', '.prefab', '.unity', '.meta', '.md'):
                relative = file.relative_to(project).as_posix().encode()
                content = file.read_bytes()
                digest.update(len(relative).to_bytes(8, 'big') + relative)
                digest.update(len(content).to_bytes(8, 'big') + content)
                count += 1
    return {'repository': str(top), 'project_root': str(project), 'branch': actual,
            'commit': git('rev-parse', 'HEAD'), 'code_fingerprint': digest.hexdigest(),
            'worktree_status': worktree_status, 'submodule_versions': submodule_versions,
            'baseline_scope': '当前本地工作区，含未提交源码；不代表远端最新',
            'fingerprint_files': count, 'unity_version': version, 'runner': str(runner),
            'fingerprint_scope': '源码、文本配置、Unity序列化与meta；不含二进制美术资源和构建',
            'capabilities': ['逐用例只读静态审查；不启动Unity或编译测试'],
            'gaps': ['二进制资源不在源码指纹内；无法读取的配置与外部服务须逐断言记录缺口',
                     '静态推导需要人工评审，不等于实机复现'],
            'executed': False}


def execute_logic(binding, evidence_root, cases=None, requirements=None, progress=None):
    if binding and binding.get('execution_suite') == 'static':
        from server.static_review import execute_static
        return execute_static(binding, cases, requirements or [], evidence_root, progress=progress)
    if binding and binding.get('execution_suite') == 'streakgroup':
        from server.streakgroup_execution import execute_streakgroup
        return execute_streakgroup(binding, evidence_root)
    if not binding or not binding.get('repository') or not binding.get('branch'):
        raise ValueError('请先绑定本地代码')
    current = inspect_project(binding['repository'], binding['branch'])
    if current['code_fingerprint'] != binding['code_fingerprint'] or current['commit'] != binding['commit']:
        raise ValueError('代码已变化，请重新绑定并确认测试范围')
    directory = Path(evidence_root).resolve() / uuid.uuid4().hex
    directory.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'server.gagasort_probe', '--repository', current['repository'],
               '--evidence', str(directory)]
    try:
        result = run_process(command, cwd=Path(__file__).resolve().parent.parent,
                                capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ValueError('逻辑探针超时，未登记通过；证据目录：' + str(directory)) from None
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'runner.log').write_text(result.stdout + result.stderr)
    if result.returncode or not (directory / 'report.json').is_file():
        raise ValueError('逻辑探针执行异常，未登记通过；证据目录：' + str(directory))
    after = inspect_project(binding['repository'], binding['branch'])
    if after['code_fingerprint'] != current['code_fingerprint'] or after['commit'] != current['commit']:
        raise ValueError('执行期间代码变化，结果已失效；证据目录：' + str(directory))
    report = json.loads((directory / 'report.json').read_text())
    normalized = normalize_report(report, 0, current['code_fingerprint'], str(directory / 'report.json'))
    normalized.update({'method': 'production_method_probe_with_stubs', 'build': None,
                       'branch': current['branch'], 'commit': current['commit'],
                       'scope': '仅固定生产方法探针；依赖使用内存替身，未运行 Unity 客户端，未建立需求用例映射'})
    (directory / 'execution.json').write_text(json.dumps(normalized, ensure_ascii=False, indent=2))
    return normalized


def inspect_ui_runner(project):
    """读取既有设计目录；不把设计模板冒充实际执行能力。"""
    import re
    path = Path(project) / 'Assets/Editor/Tools/TEST/TEST_RealGameUiSmokeWindow.cs'
    if not path.is_file():
        return {'available': False, 'templates': [], 'remote_connected': False}
    source = path.read_text()
    marker = 'private static readonly string[][] cDesign ='
    start = source.find(marker)
    if start < 0:
        raise ValueError('UI 设计目录格式已变化，需要重新检查')
    end = source.find('\n        };', start)
    if end < 0:
        raise ValueError('UI 设计目录未完整读取')
    templates = []
    pattern = r'new\[\]\s*\{\s*("(?:[^"\\]|\\.)*"),\s*("(?:[^"\\]|\\.)*"),\s*("(?:[^"\\]|\\.)*")\s*\}'
    for match in re.finditer(pattern, source[start:end]):
        title, action, expected = [json.loads(v) for v in match.groups()]
        templates.append({'id': f'UI-{len(templates)+1:03d}', 'title': title,
                          'design_action': action, 'design_expected': expected,
                          'source_line': source.count('\n', 0, start+match.start())+1,
                          'execution_status': 'not_run'})
    modes = [{'id': 'home_traversal', 'title': '首页遍历', 'requires_gm_pretreatment': True,
              'account_changes_optional': True, 'execution_status': 'not_run',
              'scope': '真实入口包含GM固定前置；不等于完整设计模板或需求用例覆盖'}]
    settings_start = source.find('if (mTraversal) BuildTraversal();')
    settings_end = source.find('            try {', settings_start)
    if settings_start >= 0 and settings_end > settings_start:
        settings = []
        for match in re.finditer(r'AddStep\(("(?:[^"\\]|\\.)*"),\s*("(?:[^"\\]|\\.)*"),\s*("(?:[^"\\]|\\.)*")', source[settings_start:settings_end]):
            title, action, expected = [json.loads(v) for v in match.groups()]
            settings.append({'title': title, 'action': action, 'expected': expected,
                             'execution_status': 'not_run',
                             'source_line': source.count('\n', 0, settings_start+match.start())+1})
        if settings:
            modes.append({'id': 'settings_smoke', 'title': '设置冒烟',
                          'requires_gm_pretreatment': False, 'account_changes_optional': False,
                          'steps': settings, 'execution_status': 'not_run',
                          'scope': '另含正式首页就绪检查；仅设置切换及恢复，不验证连胜分组'})
    return {'available': True, 'source': str(path), 'templates': templates, 'modes': modes,
            'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'remote_connected': False, 'start_entry': 'private StartRun(); Unity Editor窗口',
            'scope': '仅源码设计目录；实际ClickOnlyCase会收窄范围，未验证客户端执行，不能直接覆盖生成用例',
            'conditions': ['Unity已由用户启动并处于Play Mode', '真实GameView可聚焦',
                           'macOS输入权限', '按所选模式核对设置变更与恢复范围；首页遍历有GM固定前置']}
