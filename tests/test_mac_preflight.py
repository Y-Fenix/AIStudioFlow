import json
import os
import plistlib
import tempfile
import unittest
from pathlib import Path

from tools.mac_preflight import check_deployment


class MacPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plist = self.root / 'server.plist'
        self.caddy = self.root / 'Caddyfile'
        self.auth = self.root / 'team-auth.json'
        with self.plist.open('wb') as plist:
            plistlib.dump({
            'UserName': '_studioflow',
            'WorkingDirectory': str(self.root / 'app'),
            'ProgramArguments': ['/opt/homebrew/bin/python3', '-m', 'server.app', '--host', '127.0.0.1',
                                 '--port', '8766', '--database', str(self.root / 'data/platform.sqlite')],
            }, plist)
        self.caddy.write_text('studio.mygame.dev {\n reverse_proxy 127.0.0.1:8766\n}\n')
        self.auth.write_text(json.dumps({
            'mode': 'team', 'client_id': 'cli_test', 'client_secret': 'secret-never-print',
            'public_url': 'https://studio.mygame.dev', 'allowed_tenants': ['tenant_a'],
            'allow_all_tenants': False,
        }))
        self.auth.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_team_configuration_without_exposing_secret(self):
        errors = check_deployment(self.plist, self.caddy, self.auth)
        self.assertEqual(errors, [])

    def test_password_mode_needs_no_feishu_application_or_tenant_policy(self):
        self.auth.write_text(json.dumps({'mode': 'password', 'public_url': 'https://studio.mygame.dev',
                                        'registration_open': True}))
        self.auth.chmod(0o600)
        self.assertEqual(check_deployment(self.plist, self.caddy, self.auth), [])

    def test_rejects_insecure_bind_unmatched_host_and_unprotected_secret(self):
        config = plistlib.loads(self.plist.read_bytes())
        args = config['ProgramArguments']
        args[args.index('127.0.0.1')] = '0.0.0.0'
        self.plist.write_bytes(plistlib.dumps(config))
        self.caddy.write_text('other.example.com { reverse_proxy 127.0.0.1:8766 }')
        self.auth.chmod(0o644)

        errors = check_deployment(self.plist, self.caddy, self.auth)

        self.assertTrue(any('127.0.0.1' in error for error in errors))
        self.assertTrue(any('域名' in error for error in errors))
        self.assertTrue(any('0600' in error for error in errors))
        self.assertNotIn('secret-never-print', '\n'.join(errors))

    def test_rejects_example_paths_and_missing_tenant_policy(self):
        config = plistlib.loads(self.plist.read_bytes())
        config['WorkingDirectory'] = '/opt/studioflow/app'
        self.plist.write_bytes(plistlib.dumps(config))
        auth = json.loads(self.auth.read_text())
        auth['allowed_tenants'] = []
        self.auth.write_text(json.dumps(auth))
        self.auth.chmod(0o600)

        errors = check_deployment(self.plist, self.caddy, self.auth)

        self.assertTrue(any('占位' in error for error in errors))
        self.assertTrue(any('企业' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
