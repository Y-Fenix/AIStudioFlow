import json
import tempfile
import unittest
from pathlib import Path

from departments.testing.QA_release_contract import QA_freeze_profile
from departments.testing.QA_release_orchestrator import QA_run_release_pipeline


class QAReleaseOrchestratorTests(unittest.TestCase):
    def profile(self, root):
        repos = {}
        for name in ('client', 'android', 'ios', 'sdkserver', 'gameserver'):
            path = root / name
            path.mkdir()
            repos[name] = str(path)
        (root / 'client' / 'Assets').mkdir()
        (root / 'client' / 'Assets' / 'main.cs').write_text('class Main {}')
        (root / 'android' / 'good.js').write_text('const value = 1;')
        skills = root / 'skills'
        for name in ('test-case', 'test-codetest', 'test-server-sdk', 'gagasort-qa'):
            (skills / name).mkdir(parents=True)
            (skills / name / 'SKILL.md').write_text('输入 输出 证据 边界')
        return QA_freeze_profile(repos, skills, allowed_checks=['syntax'])

    def test_one_run_produces_resumable_report_with_runtime_gates(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = QA_run_release_pipeline(self.profile(root), root / 'run')
            self.assertEqual(result['status'], 'completed_with_findings')
            self.assertFalse(result['release_verified'])
            self.assertEqual(result['phases']['sdk_static']['status'], 'completed')
            self.assertEqual(result['phases']['project_static']['status'], 'completed')
            self.assertIn('runtime_payment', {x['id'] for x in result['risks']})
            self.assertTrue((root / 'run' / 'state.json').is_file())
            self.assertTrue((root / 'run' / 'report.json').is_file())

    def test_resume_reuses_completed_phases_and_keeps_report_stable(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile = self.profile(root)
            first = QA_run_release_pipeline(profile, root / 'run')
            second = QA_run_release_pipeline(profile, root / 'run', resume=True)
            self.assertEqual(first['run_id'], second['run_id'])
            self.assertEqual(second['phases']['sdk_static']['attempts'], 1)
            self.assertEqual(second['phases']['project_static']['attempts'], 1)
            saved = json.loads((root / 'run' / 'report.json').read_text())
            self.assertEqual(saved['run_id'], first['run_id'])

    def test_existing_run_requires_resume_explicitly(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile = self.profile(root)
            QA_run_release_pipeline(profile, root / 'run')
            with self.assertRaises(ValueError):
                QA_run_release_pipeline(profile, root / 'run', resume=False)


if __name__ == '__main__':
    unittest.main()
