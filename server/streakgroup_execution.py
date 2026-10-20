"""复用既有连胜分组定向测试；只读生产代码，编译产物在脚本临时目录。"""
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from server.processes import run

SDK = Path(__file__).resolve().parents[1]/'.runtimes/dotnet'

SUITES = [('streakgroup-domain', 'tools/test-streakgroup-event.py', '连胜分组领域逻辑', r'通过：StreakGroupEvent.*共 (\d+) 项断言'),
          ('streakgroup-rank', 'tools/test-streakgroup-rank-animation.py', '连胜分组排名动画时序', r'PASS: (\d+) 项真实 Configuration/RankList/RankCell 断言')]


def classify_result(returncode, log, summary):
    matched = re.search(summary, log)
    if returncode == 0 and matched:
        return 'passed', int(matched.group(1)), matched.group(0), 'verified_assertions'
    # 两个既有运行器的断言入口均为 Program.Check；仅非零退出不证明断言失败。
    exception = re.search(r'^Unhandled exception\. System\.Exception: ([^\r\n]+)', log, re.M)
    assertion_frame = re.search(r'^\s+at Program\.Check\((?:Boolean b, String message|Boolean ok, String why)\)', log, re.M)
    if returncode != 0 and exception and assertion_frame:
        return 'failed', None, exception.group(1), 'assertion_failure_needs_triage'
    return ('runner_error', None,
            '测试套件未取得通过摘要或可识别断言栈；需查日志归类', 'unclassified_execution_error')


def attribution_sources(repository, result_ids):
    """只读明确套件的生产源码与断言/替身；不执行运行器解析代码。"""
    root = Path(repository).resolve()
    feature = root/'GagaSort/Assets/Features/feature-streakgroupevent/Scripts'
    paths = []
    if 'streakgroup-domain' in result_ids:
        paths.extend(feature/path for path in (
            'External/Contracts/StreakGroupEventContracts.cs',
            'Internal/Config/StreakGroupEventSetting.cs', 'Internal/Config/StreakGroupConfiguration.cs',
            'Internal/Archive/StreakGroupEventArchive.cs', 'Internal/Archive/StreakGroupEventArchiveHandler.cs',
            'Internal/StreakGroupEventManager.cs', 'Internal/UI/StreakGroupEventStartPage.cs',
            'Internal/UI/StreakGroupEventExplainPage.cs', 'Internal/UI/StreakGroupEventMainPage.cs',
            'Internal/UI/HomeStreakGroupEventBtn.cs', 'Internal/Network/StreakGroupEventNetworkData.cs',
            'Internal/Network/StreakGroupEventNetworkDataSource.cs'))
        paths.extend(root/'GagaSort/Assets/Scripts'/path for path in (
            'GamePlay/ColorStreak/Core/ColorStreakProgression.cs',
            'GamePlay/Home/Logic/StateMachine/HomePreState.cs',
            'GamePlay/Home/Logic/StateMachine/HomeFlyEventRewardState.cs',
            'GamePlay/Home/Logic/StateMachine/HomeStreakGroupEventAutoOpenState.cs',
            'GamePlay/Home/Logic/StateMachine/HomeStateMachine.cs',
            'AWFramework/StateMachine/StateBase.cs', 'AWFramework/StateMachine/StateMachine.cs',
            'AWFramework/Network/NetData.cs'))
    if 'streakgroup-rank' in result_ids:
        paths.extend(feature/path for path in (
            'Internal/UI/StreakGroupEventRankList.cs', 'Internal/UI/StreakGroupEventRankCell.cs',
            'Internal/Config/StreakGroupConfiguration.cs'))
    paths.extend(root/relative for identifier, relative, _, _ in SUITES if identifier in result_ids)
    sources = {}
    for path in paths:
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ValueError('套件源码引用超出项目目录')
        sources[str(path)] = path.read_text()
    return sources


def execute_streakgroup(binding, evidence_root):
    from server.gagasort import inspect_project
    before = inspect_project(binding['repository'], binding['branch'])
    if (before['code_fingerprint'], before['commit']) != (binding['code_fingerprint'], binding['commit']):
        raise ValueError('代码已变化，请重新绑定')
    root = Path(binding['repository'])
    sdk = SDK
    if not (sdk/'dotnet').is_file():
        raise ValueError('连胜分组测试需要.NET9 SDK，请执行 tools/install-dotnet9.py')
    environment = dict(os.environ, PATH=str(sdk)+os.pathsep+os.environ.get('PATH',''),
                       DOTNET_ROOT=str(sdk), DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1',
                       UseSharedCompilation='false', MSBUILDDISABLENODEREUSE='1', DOTNET_CLI_USE_MSBUILD_SERVER='0')
    directory = Path(evidence_root).resolve()/uuid.uuid4().hex
    directory.mkdir(parents=True)
    results = []
    for identifier, relative, name, summary in SUITES:
        script = root/relative
        if not script.is_file():
            raise ValueError('缺少既有定向测试：'+relative)
        try:
            completed = run([sys.executable,str(script)],cwd=root,env=environment,
                            capture_output=True,text=True,timeout=180)
            log = (completed.stdout or '')+(completed.stderr or '')
            status, count, detail, classification = classify_result(completed.returncode, log, summary)
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            status,count,detail,log = 'runner_error',None,'定向测试超时，未登记通过','定向测试超时'
            classification, returncode = 'execution_timeout', None
        log_path = directory/(identifier+'.log')
        log_path.write_text(log)
        results.append({'id':identifier,'test_name':name,'status':status,
                        'classification':classification,'returncode':returncode,
                        'detail':detail,'evidence':str(log_path),'assertion_count':count,
                        'source_runner':str(script),'scope':'套件级生产代码断言；依赖为替身，不等于需求用例或客户端通过'})
    after = inspect_project(binding['repository'], binding['branch'])
    if (before['code_fingerprint'],before['commit']) != (after['code_fingerprint'],after['commit']):
        raise ValueError('执行期间代码已变化，结果失效；证据：'+str(directory))
    report = {'results':results,'counts':{status:sum(r['status']==status for r in results) for status in ('passed','failed','runner_error')},
              'method':'production_suite_with_stubs','build':None,'branch':before['branch'],'commit':before['commit'],
              'code_fingerprint':before['code_fingerprint'],'evidence':str(directory/'execution.json'),
              'scope':'连胜分组领域和排名动画定向套件；通过数按套件统计，断言数另列；未执行Unity客户端，未自动证明需求用例覆盖'}
    (directory/'execution.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report
