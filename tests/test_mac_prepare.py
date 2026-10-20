import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

class MacPrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=self.root/'Game Studio App';(self.app/'server').mkdir(parents=True);(self.app/'web').mkdir()
        (self.app/'server/app.py').write_text('# fixture');(self.app/'web/index.html').write_text('fixture')
        self.account=SimpleNamespace(pw_name='studio_service',pw_uid=502,pw_gid=20,pw_dir=str(self.root/'Service Home'))

    def prepare(self,**kwargs):
        from tools.mac_prepare import prepare_deployment
        options={'app_root':self.app,'public_url':'https://studio.mygame.dev','service_user':'studio_service','output_dir':self.root/'prepared','python_path':sys.executable}
        options.update(kwargs)
        with patch('tools.mac_prepare.pwd.getpwnam',return_value=self.account):return prepare_deployment(**options)

    def test_resolves_real_paths_spaces_account_home_and_passes_existing_preflight(self):
        folder=self.prepare()
        config=plistlib.loads((folder/'com.studioflow.server.plist').read_bytes());args=config['ProgramArguments']
        self.assertEqual(config['WorkingDirectory'],str(self.app.resolve()))
        self.assertEqual(config['UserName'],'studio_service')
        expected=str(Path(self.account.pw_dir)/'Library/Application Support/StudioFlow/platform.sqlite')
        self.assertEqual(args[args.index('--database')+1],expected)
        self.assertEqual(config['EnvironmentVariables']['CODEX_HOME'],str(Path(self.account.pw_dir)/'.codex'))
        self.assertFalse(Path(self.account.pw_dir).exists(),'generation must not create or modify runtime directories')
        auth=self.root/'team-auth.json';auth.write_text(json.dumps({'mode':'team','client_id':'fixture','client_secret':'do-not-copy-or-print','public_url':'https://studio.mygame.dev','allowed_tenants':['tenant-a']}));auth.chmod(0o600)
        from tools.mac_preflight import check_deployment
        self.assertEqual(check_deployment(folder/'com.studioflow.server.plist',folder/'Caddyfile',auth),[])
        self.assertNotIn('do-not-copy-or-print',''.join(p.read_text() for p in folder.iterdir()))
        self.assertNotIn('/auth/feishu/callback',(folder/'DEPLOY.md').read_text())
        self.assertIn('设置负责人账号',(folder/'DEPLOY.md').read_text())
        self.assertEqual(json.loads((folder/'deployment.json').read_text())['auth_mode'], 'password')
        self.assertEqual(os.stat(folder).st_mode&0o777,0o700)

    def test_rejects_injection_root_account_and_invalid_runtime_without_partial_output(self):
        for url in ('http://studio.mygame.dev','https://studio.mygame.dev/evil','https://user:pass@studio.mygame.dev','https://studio.mygame.dev\n{\n respond pwned\n}','https://localhost','https://studio.example.com','https://studio.mygame.dev:8443'):
            with self.subTest(url=url),self.assertRaises(ValueError):self.prepare(public_url=url)
            self.assertFalse((self.root/'prepared').exists())
        self.account.pw_uid=0
        with self.assertRaisesRegex(ValueError,'root'):self.prepare()
        self.account.pw_uid=502
        with self.assertRaises(ValueError):self.prepare(python_path='/no/such/python')
        self.assertFalse((self.root/'prepared').exists())

    def test_existing_folder_is_not_overwritten_and_custom_runtime_paths_are_explicit(self):
        folder=self.prepare(data_dir=self.root/'Data Dir',log_dir=self.root/'Logs Dir',codex_home=self.root/'Codex Dir')
        config=plistlib.loads((folder/'com.studioflow.server.plist').read_bytes())
        self.assertEqual(config['EnvironmentVariables']['CODEX_HOME'],str((self.root/'Codex Dir').resolve()))
        before={p.name:p.read_bytes() for p in folder.iterdir()}
        with self.assertRaises(FileExistsError):self.prepare()
        self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir()})
