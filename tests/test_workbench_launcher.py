import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchLauncherTests(unittest.TestCase):
    def run_launcher(self, healthy):
        with tempfile.TemporaryDirectory() as folder:
            bin_dir = Path(folder)
            for name, body in {
                'curl': 'echo \'{"mode":"team"}\'; exit 0' if healthy else 'exit 7',
                'lsof': 'echo 123; exit 0',
                'open': 'exit 0',
            }.items():
                path = bin_dir / name
                path.write_text('#!/bin/sh\n' + body + '\n')
                path.chmod(0o755)
            env = {**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH'],
                   'STUDIOFLOW_OPEN_BROWSER': '0', 'STUDIOFLOW_NO_PAUSE': '1'}
            return subprocess.run(['/bin/zsh', str(ROOT / '启动工作台.command')],
                                  env=env, text=True, capture_output=True, timeout=10)

    def test_reuses_running_service(self):
        result = self.run_launcher(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('已在运行', result.stdout)

    def test_refuses_occupied_port(self):
        result = self.run_launcher(False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('占用', result.stdout)
