import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from server.gagasort import inspect_project, execute_logic


class BindingTests(unittest.TestCase):
    def test_changed_code_never_launches_probe(self):
        binding = {'repository': '/fixture', 'branch': 'master', 'commit': 'old', 'code_fingerprint': 'old'}
        with patch('server.gagasort.inspect_project', return_value={**binding, 'code_fingerprint': 'new'}), patch('server.gagasort.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, '代码已变化'):
                execute_logic(binding, '/unused')
            run.assert_not_called()

    def test_readonly_git_and_uncommitted_source_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            project=root/'GagaSort'
            (project/'ProjectSettings').mkdir(parents=True)
            (project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 2022.3\n')
            runner=project/'Assets/Editor/Tools/TEST/TEST_test-business-automation.py'
            runner.parent.mkdir(parents=True)
            runner.write_text('# fixture')
            def git(command, **kwargs):
                outputs={'--show-toplevel': folder, 'HEAD': 'master'}
                value=folder if '--show-toplevel' in command else 'master' if 'symbolic-ref' in command else 'commit1'
                self.assertFalse(any(x in command for x in ('fetch','pull','checkout','commit','push')))
                return SimpleNamespace(returncode=0,stdout=value)
            with patch('server.gagasort.subprocess.run',side_effect=git):
                first=inspect_project(folder,'master')
                runner.write_text('# changed fixture')
                second=inspect_project(folder,'master')
                self.assertNotEqual(first['code_fingerprint'],second['code_fingerprint'])
                self.assertFalse(second['executed'])
                with self.assertRaisesRegex(ValueError,'分支不一致'):
                    inspect_project(folder,'release')


class UiCatalogTests(unittest.TestCase):
    def test_catalog_is_design_only_and_never_claims_runtime_pass(self):
        import tempfile
        from server.gagasort import inspect_ui_runner
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'Assets/Editor/Tools/TEST/TEST_RealGameUiSmokeWindow.cs'
            p.parent.mkdir(parents=True)
            p.write_text('private static readonly string[][] cDesign = {\n new[] { "连胜页面", "点击说明", "恢复首页" },\n        };')
            result=inspect_ui_runner(folder)
            self.assertEqual(result['templates'][0]['id'],'UI-001')
            self.assertEqual(result['templates'][0]['execution_status'],'not_run')
            self.assertFalse(result['remote_connected'])
            self.assertTrue(result['source_sha256'])
            p.write_text('changed')
            with self.assertRaises(ValueError):inspect_ui_runner(folder)
