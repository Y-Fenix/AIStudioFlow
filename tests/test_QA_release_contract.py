import tempfile
import unittest
from pathlib import Path

from departments.testing.QA_release_contract import QA_freeze_profile, QA_verify_profile


class QA_ReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repos = {}
        for name in ('client', 'android', 'ios', 'sdkserver', 'gameserver'):
            folder = self.root / name
            folder.mkdir()
            self.repos[name] = str(folder)
        self.skills = self.root / 'skills'
        self.skills.mkdir()
        for name in ('test-case', 'test-codetest', 'test-server-sdk', 'gagasort-qa'):
            folder = self.skills / name
            folder.mkdir()
            (folder / 'SKILL.md').write_text('rules', encoding='utf-8')
            (folder / 'helper.py').write_text('value = 1', encoding='utf-8')

    def freeze(self, **kwargs):
        return QA_freeze_profile(self.repos, self.skills, **kwargs)

    def test_freeze_hashes_dependencies_and_detects_changes(self):
        frozen = self.freeze()
        self.assertTrue(QA_verify_profile(frozen)['valid'])
        (self.skills / 'test-case' / 'helper.py').write_text('value = 2')
        result = QA_verify_profile(frozen)
        self.assertFalse(result['valid'])
        self.assertIn('skill_package_changed:test-case', result['gaps'])

    def test_no_implicit_tool_or_external_write_authorization(self):
        frozen = self.freeze()
        self.assertEqual(frozen['allowed_checks'], ['source_review'])
        self.assertFalse(frozen['external_publication'])
        with self.assertRaises(ValueError):
            self.freeze(allowed_checks=['shell'])

    def test_missing_repository_is_explicit_and_blocks_preflight(self):
        Path(self.repos['ios']).rmdir()
        frozen = self.freeze()
        self.assertFalse(frozen['repositories']['ios']['available'])
        self.assertIn('repository_unavailable:ios', QA_verify_profile(frozen)['gaps'])

    def test_symlink_skill_dependency_and_overlapping_repos_rejected(self):
        (self.skills / 'test-case' / 'escape').symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.freeze()
        (self.skills / 'test-case' / 'escape').unlink()
        self.repos['ios'] = self.repos['android']
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.freeze()

    def test_changed_or_forged_manifest_cannot_resume(self):
        frozen = self.freeze()
        frozen['allowed_checks'].append('shell')
        self.assertFalse(QA_verify_profile(frozen)['valid'])
