#!/usr/bin/env python3
"""Contract tests: CLI calls are mocked, never write a real Feishu table."""
import json
import subprocess
import unittest
from unittest.mock import patch
from feishu_bridge import Bridge, REQUIRED_SCOPES, envelope, normalize_field

URL = 'https://example.feishu.cn/base/ABC?table=tbl_fixture'


class FeishuBridgeTests(unittest.TestCase):
    def test_codex_module_created_before_bug_and_keeps_existing_options(self):
        field = {'id':'mod','name':'功能模块','type':'select','multiple':False,
                 'default_value':['【基础规则】'], 'options':[{'name':'【基础规则】','hue':'Blue'}]}
        bridge, _ = self.bridge([field])
        calls = []
        original_run = bridge.run
        def run(args, timeout=120):
            calls.append(args)
            if '+field-get' in args:
                return {'ok':True,'data':{'field':field}}
            if '+field-update' in args:
                body = json.loads(args[args.index('--json')+1])
                self.assertNotIn('id', body)
                self.assertEqual(body['options'][0], {'name':'【基础规则】','hue':'Blue'})
                self.assertEqual(body['default_value'], ['【基础规则】'])
                field.update(body)
                return {'ok':True,'data':{'updated':True}}
            return original_run(args, timeout)
        bridge.run = run
        self.assertEqual(bridge.records(URL,[{'功能模块':'✅三阶段竞速比赛'}]), {'submitted':1,'total':1})
        body = json.loads(calls[-1][calls[-1].index('--json')+1])
        self.assertEqual(body['create_records'][0]['功能模块'], '【Codex-三阶段竞速比赛】')
        self.assertEqual(sum('+field-update' in args for args in calls), 1)
        self.assertEqual(sum('+field-get' in args for args in calls), 2)

    def test_module_create_denied_does_not_submit_bug(self):
        bridge, calls = self.bridge([{'id':'mod','name':'功能模块','type':'select','options':[]}])
        original_run = bridge.run
        def run(args, timeout=120):
            if '+field-get' in args:
                return {'ok':True,'data':{'field':{'name':'功能模块','type':'select','options':[]}}}
            if '+field-update' in args:
                raise RuntimeError('权限不足')
            return original_run(args, timeout)
        bridge.run = run
        with self.assertRaisesRegex(RuntimeError,'权限不足'):
            bridge.records(URL,[{'功能模块':'三阶段竞速比赛'}])
        self.assertFalse(any('+record-batch-create' in args for args in calls))

    def bridge(self, fields=None, visible=None, created=None):
        bridge = Bridge('fixture-lark')
        calls = []
        def run(args, timeout=120):
            calls.append(args)
            if '+url-resolve' in args:
                return {'ok': True, 'data': {'base_token': 'bascn_fixture', 'table_id': 'tbl_fixture'}}
            if '+field-list' in args:
                return {'ok': True, 'data': {'fields': fields or [{'id': 'f1', 'name': '缺陷描述', 'type': 'text'}]}}
            if '+view-get-visible-fields' in args:
                return {'ok': True, 'data': {'field_ids': visible}}
            return {'ok': True, 'data': created if created is not None else {'record_id_list': ['rec_fixture']}}
        bridge.run = unittest.mock.Mock(side_effect=run)
        return bridge, calls

    def test_envelope_surrounding_notice(self):
        self.assertTrue(envelope('notice\n{"ok":true}\n')['ok'])

    def test_error_envelope_on_stderr(self):
        bridge = Bridge('fixture')
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', '{"ok":false,"error":{"message":"真实错误"}}')):
            with self.assertRaisesRegex(RuntimeError, '真实错误'):
                bridge.run(['base'])

    def test_validate_url(self):
        for host in ['a.feishu.cn','example.larksuite.com','example.larkoffice.com']:
            Bridge.validate_url('https://'+host+'/wiki/ABC')
        for value in ['http://example.feishu.cn/base/ABC','https://feishu.cn.evil.test/base/X','https://feishu.cn@evil.test/base/X','https://a.feishu.cn/docs/X']:
            with self.assertRaises(ValueError): Bridge.validate_url(value)

    def test_fields_numeric_and_multiple_options(self):
        bridge, calls = self.bridge([{'field_id': 'f1', 'field_name': '缺陷描述', 'type': 1},
                                    {'field_id': 'f2', 'field_name': '标签', 'type': 4, 'property': {'options': [{'name':'已证'}]}}])
        schema = bridge.fields(URL)
        self.assertEqual(schema['headers'], ['缺陷描述','标签'])
        self.assertTrue(schema['fields'][1]['multiple'])
        self.assertEqual(schema['fields'][1]['options'], ['已证'])
        self.assertTrue(all(args[args.index('--as')+1]=='user' for args in calls))

    def test_view_order_mixed_ids_and_names(self):
        bridge, _ = self.bridge([{'id':'f1','name':'标题','type':'text'},{'id':'f2','name':'空列','type':'text'}], ['f2',{'name':'标题'}])
        self.assertEqual(bridge.fields(URL+'&view=vew')['headers'], ['空列','标题'])

    def test_unknown_view_field_does_not_silently_drop_column(self):
        bridge, _ = self.bridge(visible=['f1','missing'])
        with self.assertRaisesRegex(RuntimeError, '不能丢列'): bridge.fields(URL+'&view=vew')

    def test_partial_field_list_rejected(self):
        bridge = Bridge('fixture')
        with patch.object(bridge, 'run', side_effect=[{'data':{'base_token':'b','table_id':'t'}},{'data':{'items':[], 'has_more':True}}]):
            with self.assertRaisesRegex(RuntimeError,'不能截断'): bridge.fields(URL)

    def test_dashboard_not_mistaken_for_table(self):
        bridge = Bridge('fixture')
        with patch.object(bridge, 'run', return_value={'data':{'base_token':'b','selected_block_id':'dashboard'}}):
            with self.assertRaisesRegex(RuntimeError,'数据表'): bridge.fields(URL)

    def test_typed_write_filters_readonly_empty_and_uses_user(self):
        bridge, calls = self.bridge([{'name':'标题','type':'text'},{'name':'数值','type':'number'},
            {'name':'标签','type':'select','multiple':True,'options':['已证']}, {'name':'公式','type':'formula'}])
        result = bridge.records(URL,[{'标题':'真实问题','数值':'3','标签':'已证','公式':'不写','空列':''}],['标题','数值','标签','公式'])
        self.assertEqual(result, {'submitted':1,'total':1})
        command=calls[-1]
        body=json.loads(command[command.index('--json')+1])
        self.assertEqual(body,{'create_records':[{'标题':'真实问题','数值':3,'标签':['已证']}]})
        self.assertEqual(command[command.index('--as')+1],'user')

    def test_invalid_select_or_number_stops_before_write(self):
        for kind,value in [('select','新选项'),('number','不是数值'),('checkbox','未解决')]:
            bridge,calls=self.bridge([{'name':'目标','type':kind,'options':['已证']}])
            with self.assertRaises(ValueError): bridge.records(URL,[{'目标':value}])
            self.assertFalse(any('+record-batch-create' in c for c in calls))

    def test_changed_headers_stops_before_write(self):
        bridge,calls=self.bridge()
        with self.assertRaisesRegex(ValueError,'表头已变化'): bridge.records(URL,[{'缺陷描述':'bug'}],['标题'])
        self.assertEqual(len(calls),2)

    def test_success_requires_all_record_ids_and_no_ignored_fields(self):
        for data in [{}, {'record_id_list':[]}, {'record_id_list':['rec'],'ignored_fields':['标题']}]:
            bridge,_=self.bridge(created=data)
            with self.assertRaisesRegex(RuntimeError,'勿重复提交'): bridge.records(URL,[{'缺陷描述':'bug'}])

    def test_timeout_does_not_claim_no_writes(self):
        bridge,_=self.bridge()
        schema=bridge.fields(URL)
        with patch.object(bridge,'fields',return_value=schema),patch.object(bridge,'run',side_effect=subprocess.TimeoutExpired('fixture',1)):
            with self.assertRaisesRegex(RuntimeError,'可能已写入'): bridge.records(URL,[{'缺陷描述':'bug'}])

    def test_limits_before_cli(self):
        bridge=Bridge('fixture')
        with patch.object(bridge,'run') as run:
            for records in [[],[{}]*201]:
                with self.assertRaises(ValueError): bridge.records(URL,records)
            run.assert_not_called()

    def test_auth_reuses_refreshable_scoped_session(self):
        bridge=Bridge('fixture')
        for token_status in ['valid','needs_refresh']:
            with patch.object(bridge,'run',return_value={'identities':{'user':{'tokenStatus':token_status,'scope':' '.join(REQUIRED_SCOPES)}}}):
                result=bridge.auth_status()
                self.assertEqual(result['status'],'authorized')
                self.assertNotIn('token',result)
        with patch.object(bridge,'run',return_value={'identities':{'user':{'tokenStatus':'valid','scope':'base:field:read'}}}):
            self.assertIn('base:record:create',bridge.auth_status()['error'])


if __name__ == '__main__': unittest.main()
