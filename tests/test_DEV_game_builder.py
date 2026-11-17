import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from departments.development.DEV_game_builder import DEV_build_game, DEV_normalize_spec, DEV_prepare_root, DEV_verify_android, DEV_run


class DEV_GameBuilderTests(unittest.TestCase):
    def test_rejects_unsupported_game_without_substitution(self):
        with self.assertRaisesRegex(ValueError, 'memory_match'):
            DEV_normalize_spec({'game_type': 'racing'})
        with self.assertRaisesRegex(ValueError, 'memory_match'):
            DEV_normalize_spec({})

    def test_parameter_bounds_and_untrusted_title(self):
        spec = DEV_normalize_spec({'game_type': 'memory_match', 'title': '"; evil()', 'pairs': 100, 'time_limit_seconds': 1})
        self.assertEqual(spec['pairs'], 8)
        self.assertEqual(spec['time_limit_seconds'], 30)
        self.assertEqual(spec['title'], '"; evil()')

    def test_root_rejects_existing_content_and_symlink_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'occupied').mkdir()
            (root / 'occupied' / 'keep').write_text('user')
            with self.assertRaises(ValueError):
                DEV_prepare_root(root / 'occupied')
            (root / 'link').symlink_to(root / 'occupied', target_is_directory=True)
            with self.assertRaises(ValueError):
                DEV_prepare_root(root / 'link' / 'new')

    def test_cancel_before_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder).resolve() / 'new'
            def cancel():
                raise RuntimeError('cancelled')
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                DEV_build_game(output, 'memory game', check_cancelled=cancel)
            self.assertFalse(output.exists())

    def test_never_installs_on_real_phone(self):
        with self.assertRaisesRegex(ValueError, '模拟器'):
            DEV_verify_android('/unused', 'example', {}, {}, serial='real-phone-id')

    def test_rejects_model_unsupported_without_running_commands(self):
        class DEV_Model:
            def request_json(self, prompt):
                return {'game_type': 'unsupported'}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder).resolve() / 'new'
            with patch('departments.development.DEV_game_builder.DEV_discover_tools', return_value={}):
                with self.assertRaisesRegex(ValueError, 'memory_match'):
                    DEV_build_game(output, 'a racing simulator', model=DEV_Model())
            self.assertTrue((output / 'failure.json').is_file())
            self.assertFalse((output / 'src').exists())

    def test_running_process_is_terminated_on_cancellation(self):
        import sys
        calls = 0
        def DEV_cancel():
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise RuntimeError('cancelled')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                DEV_run([sys.executable, '-c', 'import time; time.sleep(30)'], root, root / 'log', check_cancelled=DEV_cancel)
