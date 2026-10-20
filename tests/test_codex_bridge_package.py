import platform
import plistlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_codex_bridge import build_bridge


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('swiftc'), 'requires macOS Swift compiler')
class CodexBridgePackageTests(unittest.TestCase):
    def test_package_is_installable_app_with_executable_and_declared_macos_minimum(self):
        with tempfile.TemporaryDirectory() as temp:
            package = build_bridge(Path(temp) / 'release')
            with zipfile.ZipFile(package['archive']) as archive:
                names = archive.namelist()
                bundle = 'StudioFlow Codex Bridge.app/Contents/'
                info = plistlib.loads(archive.read(bundle + 'Info.plist'))
                executable = bundle + 'MacOS/StudioFlowCodexBridge'
                self.assertIn(executable, names)
                self.assertEqual(info['LSMinimumSystemVersion'], '13.0')
                self.assertEqual(info['CFBundleIdentifier'], 'studioflow.codex-bridge')
                self.assertEqual(info['CFBundleURLTypes'][0]['CFBundleURLSchemes'], ['studioflow-codex'])
                self.assertTrue((archive.getinfo(executable).external_attr >> 16) & 0o111)
                self.assertFalse(any('team-auth' in name or name.endswith('.sqlite') for name in names))
                archive.extractall(Path(temp) / 'extracted')
            binary = Path(temp) / 'extracted' / executable
            loads = subprocess.check_output(['/usr/bin/otool', '-l', str(binary)], text=True)
            self.assertIn('minos 13.0', loads)
            self.assertEqual(len(package['sha256']), 64)
            self.assertEqual(package['architecture'], platform.machine())


if __name__ == '__main__':
    unittest.main()
