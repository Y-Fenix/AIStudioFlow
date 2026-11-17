"""Read-only release checks composed from project-local skill scripts."""
import importlib.util
import json
from pathlib import Path

from .QA_release_contract import QA_verify_profile

QA_PROJECT_ROOT = Path(__file__).resolve().parents[2]
QA_BASELINE_SCRIPT = QA_PROJECT_ROOT / '.agents' / 'skills' / 'test-server-sdk' / 'scripts' / 'baseline.py'
QA_TOOLS_SCRIPT = QA_PROJECT_ROOT / '.agents' / 'skills' / 'test-server-sdk' / 'scripts' / 'static_tools.py'


def QA_load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError('local check script cannot be loaded: ' + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def QA_run_release_checks(profile, report_dir):
    verification = QA_verify_profile(profile)
    if not verification['valid']:
        raise ValueError('profile is stale or invalid: ' + ', '.join(verification['gaps']))
    if 'syntax' not in profile['allowed_checks']:
        return {'status': 'blocked', 'release_verified': False,
                'gaps': ['syntax_check_not_authorized'], 'checks': {}}
    report_dir = Path(report_dir).expanduser().resolve()
    if report_dir.exists():
        raise ValueError('report directory already exists')
    report_dir.mkdir(parents=True)
    baseline = QA_load_module(QA_BASELINE_SCRIPT, 'QA_local_baseline')
    roots = {name: item['root'] for name, item in profile['repositories'].items()
             if name != 'client'}
    # The SDK skill's four-repository baseline is deliberately separate from the optional client.
    baseline_path = report_dir / 'baseline.json'
    payload = {'android': roots['android'], 'ios': roots['ios'],
               'sdkserver': roots['sdkserver'], 'gameserver': roots['gameserver']}
    repos = baseline.snapshot(payload)
    baseline_doc = {'schema_version': 1, 'repositories': repos,
                    'policy': {'source': 'project-local test-server-sdk baseline.py'}}
    baseline_path.write_text(json.dumps(baseline_doc, ensure_ascii=False, indent=2) + '\n')
    tools = QA_load_module(QA_TOOLS_SCRIPT, 'QA_local_static_tools')
    tool_dir = report_dir / 'tools'
    tool_payload = tools.audit(baseline_doc, tool_dir)
    exit_code = 0 if tool_payload['complete'] else (2 if tool_payload['counts'].get('syntax_error') else 3)
    tool_result = json.loads((tool_dir / 'tool-results.json').read_text())
    counts = {}
    for row in tool_result['checks']:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    current = baseline.snapshot(payload)
    changed = [name for name in repos if repos[name] != current[name]
               or repos[name].get('errors') or current[name].get('errors')]
    verification = {'stable': not changed, 'changed_repositories': changed}
    (report_dir / 'baseline-verification.json').write_text(json.dumps(
        {**verification, 'release_verified': False}, ensure_ascii=False, indent=2) + '\n')
    result = {'status': 'completed_with_findings' if exit_code else 'completed',
              'release_verified': False,
              'checks': {'syntax': {'status': 'executed', 'exit_code': exit_code,
                                     'counts': counts, 'results_file': 'tools/tool-results.json'}},
              'gaps': ['runtime_payment_analytics_ads_installation_unverified'],
              'scope': {'repositories': sorted(profile['repositories']),
                        'source_baseline': 'captured', 'client_included_in_syntax': False}}
    if not verification.get('stable'):
        result['status'] = 'stale'
        result['gaps'].append('source_changed_during_review')
    (report_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result
