#!/usr/bin/env python3
import contextlib
import io
import json
import unittest
from unittest.mock import patch
import ensure_feishu_auth as auth


class EnsureFeishuAuthTests(unittest.TestCase):
    def test_module_creation_requires_valid_field_update_scope(self):
        self.assertIn('base:field:update', auth.REQUIRED_SCOPES)
        self.assertNotIn('base:field:write', auth.REQUIRED_SCOPES)
        scopes = ' '.join(s for s in auth.REQUIRED_SCOPES if s != 'base:field:update')
        status = {'identities': {'user': {'tokenStatus': 'valid', 'scope': scopes}}}
        with patch.object(auth, 'run', return_value=status):
            self.assertFalse(auth.is_ready('fixture'))

    def test_scoped_valid_and_refreshable_sessions_skip_login(self):
        for token_status in ['valid','needs_refresh']:
            status={'identities':{'user':{'tokenStatus':token_status,'scope':auth.REQUIRED_SCOPE_TEXT}}}
            with patch.object(auth,'run',return_value=status) as run:
                self.assertTrue(auth.is_ready('fixture'))
            run.assert_called_once_with('fixture',['auth','status','--json'])

    def test_missing_create_scope_is_not_ready(self):
        with patch.object(auth,'run',return_value={'identities':{'user':{'tokenStatus':'valid','scope':'base:field:read'}}}):
            self.assertFalse(auth.is_ready('fixture'))

    def test_new_login_returns_link_without_blocking_device_poll(self):
        login={'data':{'verification_url':'https://example.feishu.cn/verify','device_code':'fixture-device'}}
        with patch.object(auth,'run',return_value=login) as run,patch.object(auth,'make_qr',return_value=False),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(auth.start('fixture',auth.Path('/tmp/fixture.png')),3)
        self.assertEqual(run.call_count,1)
        self.assertIn('base:record:create',run.call_args.args[1][3])
        self.assertNotIn('base:record:write',run.call_args.args[1][3])
        self.assertEqual(json.loads(output.getvalue())['status'],'authorization_required')
        self.assertNotIn('access_token',output.getvalue())

    def test_health_requires_protocol_version(self):
        for protocol,expected in [(1,False),(auth.BRIDGE_PROTOCOL,True)]:
            with patch.object(auth,'urlopen') as urlopen:
                urlopen.return_value.__enter__.return_value.read.return_value=json.dumps({'ok':True,'service':'gagasort-feishu-bridge','protocol':protocol}).encode()
                self.assertEqual(auth.bridge_is_ready(17321),expected)


if __name__ == '__main__': unittest.main()
