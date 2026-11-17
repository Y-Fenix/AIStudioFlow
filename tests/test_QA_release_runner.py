import json
import tempfile
import unittest
from pathlib import Path

from departments.testing.QA_release_contract import QA_freeze_profile
from departments.testing.QA_release_runner import QA_run_release_checks


class QA_ReleaseRunnerTests(unittest.TestCase):
    def test_runs_only_allowed_local_checks_and_keeps_gaps(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            repos = {}
            for name in ('client', 'android', 'ios', 'sdkserver', 'gameserver'):
                repos[name] = str(root / name)
                Path(repos[name]).mkdir()
            (Path(repos['android']) / 'ok.js').write_text('const answer = 42;')
            (Path(repos['ios']) / 'bad.js').write_text('const = ;')
            (Path(repos['sdkserver']) / 'Unsupported.kt').write_text('fun main() {}')
            skills = root / 'skills'
            for name in ('test-case', 'test-codetest', 'test-server-sdk', 'gagasort-qa'):
                (skills / name).mkdir(parents=True)
                (skills / name / 'SKILL.md').write_text('rules')
            profile = QA_freeze_profile(repos, skills, allowed_checks=['syntax'])
            result = QA_run_release_checks(profile, root / 'report')
            self.assertEqual(result['status'], 'completed_with_findings')
            self.assertEqual(result['checks']['syntax']['status'], 'executed')
            self.assertGreaterEqual(result['checks']['syntax']['counts']['syntax_error'], 1)
            self.assertGreaterEqual(result['checks']['syntax']['counts']['unsupported'], 1)
            self.assertTrue((root / 'report' / 'baseline.json').exists())
            self.assertTrue((root / 'report' / 'tools' / 'tool-results.json').exists())
            self.assertFalse(result['release_verified'])

    def test_invalid_profile_does_not_create_report(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaises(ValueError):
                QA_run_release_checks({'bad': True}, root / 'report')
            self.assertFalse((root / 'report').exists())
