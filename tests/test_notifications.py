import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server.store import Store

HOOK='https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000001'

class NotificationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=Store(Path(self.temp.name)/'test.sqlite')
  self.studio=self.store.studios()[0]['id'];self.project=self.store.create_project('通知样例')['id']
 def settings(self):
  from server.core.notification_settings import NotificationSettings
  return NotificationSettings(self.store)
 def configure(self,**extra):
  return self.settings().save(self.studio,'',{'enabled':True,'webhook':HOOK,**extra})
 def queue(self):
  from server.core.notifications import enqueue
  with self.store.connection() as db:
   return enqueue(self.store,db,self.project,'testing:0','fixture:run1','completed',{'cases':[]},origin='agent')
 def test_settings_are_private_scoped_and_inherited(self):
  value=self.configure()
  self.assertTrue(value['effective']['enabled']);self.assertNotIn(HOOK,json.dumps(value))
  self.assertEqual(os.stat(self.settings().path).st_mode&0o777,0o600)
  inherited=self.settings().get(self.studio,self.project)
  self.assertEqual(inherited['effective']['source'],'工作室默认')
  self.settings().save(self.studio,self.project,{'enabled':False})
  self.assertFalse(self.settings().get(self.studio,self.project)['effective']['enabled'])
  self.settings().save(self.studio,self.project,{'inherit':True})
  self.assertTrue(self.settings().get(self.studio,self.project)['effective']['enabled'])
 def test_project_config_identifies_its_context_and_explicit_mode(self):
  self.configure(destination_name='工作室通知群')
  inherited=self.settings().get(self.studio,self.project)
  self.assertEqual(inherited['mode'],'inherit')
  self.assertEqual(inherited['context']['project_name'],'通知样例')
  self.assertEqual(inherited['effective']['destination_name'],'工作室通知群')
  value=self.settings().save(self.studio,self.project,{'mode':'independent','enabled':True,'webhook':HOOK[:-1]+'2','destination_name':'项目 A 群'})
  self.assertEqual(value['mode'],'independent')
  self.assertEqual(value['effective']['destination_name'],'项目 A 群')
  self.assertNotIn(HOOK[:-1]+'2',json.dumps(value))
 def test_new_independent_config_requires_own_webhook(self):
  self.configure(secret='studio-secret')
  with self.assertRaisesRegex(ValueError,'Webhook'):
   self.settings().save(self.studio,self.project,{'mode':'independent','enabled':True})
  self.assertFalse(self.settings().get(self.studio,self.project)['override'])
 def test_partial_project_override_cannot_inherit_destination_in_independent_mode(self):
  self.configure(secret='studio-secret')
  settings=self.settings();data=settings.read()
  data['rules'][settings.key(self.studio,self.project)]={'enabled':False}
  settings.path.write_text(json.dumps(data))
  with self.assertRaisesRegex(ValueError,'Webhook'):
   self.settings().save(self.studio,self.project,{'mode':'independent'})
  self.assertEqual(self.settings().effective(self.studio,self.project)['webhook'],HOOK)
  self.settings().save(self.studio,self.project,{'mode':'independent','webhook':HOOK[:-1]+'2'})
  self.assertEqual(self.settings().effective(self.studio,self.project)['secret'],'')
 def test_new_destination_never_copies_old_or_inherited_signing_secret(self):
  self.configure(secret='studio-secret')
  self.settings().save(self.studio,self.project,{'mode':'independent','enabled':True,'webhook':HOOK[:-1]+'2'})
  config=self.settings().effective(self.studio,self.project)
  self.assertEqual(config['secret'],'')
  self.settings().save(self.studio,self.project,{'secret':'project-secret'})
  self.settings().save(self.studio,self.project,{'mode':'independent','webhook':HOOK[:-1]+'3'})
  self.assertEqual(self.settings().effective(self.studio,self.project)['secret'],'')
  self.assertEqual(self.settings().effective(self.studio)['secret'],'studio-secret')
 def test_invalid_or_conflicting_modes_cannot_change_destination(self):
  self.configure()
  for body in [{'mode':'unknown'},{'mode':'independent','inherit':True},{'mode':'inherit','webhook':HOOK[:-1]+'2'},{'mode':'independent','destination_name':123}]:
   with self.subTest(body=body),self.assertRaises(ValueError):
    self.settings().save(self.studio,self.project,body)
  self.assertFalse(self.settings().get(self.studio,self.project)['override'])
 def test_distinct_projects_send_to_their_own_destination_and_history(self):
  from server.core.notifications import enqueue,NotificationQueue
  other=self.store.create_project('项目 B')['id'];hook_b=HOOK[:-1]+'2'
  self.configure()
  self.settings().save(self.studio,self.project,{'mode':'independent','enabled':True,'webhook':HOOK,'destination_name':'A 群'})
  self.settings().save(self.studio,other,{'mode':'independent','enabled':True,'webhook':hook_b,'destination_name':'B 群'})
  self.queue()
  with self.store.connection() as db:enqueue(self.store,db,other,'testing:0','fixture:B1','completed',{})
  q=NotificationQueue(self.store)
  with patch('server.core.notifications.send_card') as send:
   q.run_once();q.run_once()
  self.assertEqual([c.args[0]['webhook'] for c in send.call_args_list],[HOOK,hook_b])
  self.assertEqual(len(q.listing(self.studio,self.project)),1)
  self.assertEqual(len(q.listing(self.studio,other)),1)
  self.queue()
  with self.store.connection() as db:enqueue(self.store,db,other,'testing:0','fixture:B2','completed',{})
  self.settings().save(self.studio,self.project,{'enabled':False})
  with patch('server.core.notifications.send_card') as send:q.run_once();send.assert_called_once();self.assertEqual(send.call_args.args[0]['webhook'],hook_b)
  self.settings().save(self.studio,self.project,{'mode':'inherit'})
  self.assertEqual(self.settings().effective(self.studio,other)['webhook'],hook_b)
  with self.assertRaises(KeyError):q.resend(self.studio,self.project,q.listing(self.studio,other)[0]['id'])
 def test_only_exact_feishu_hook_and_optional_signing_secret(self):
  for url in ['http://open.feishu.cn/open-apis/bot/v2/hook/x',HOOK+'?token=leak',HOOK.replace('open.feishu.cn','evil.example'),HOOK.replace('open.feishu.cn','open.feishu.cn@127.0.0.1')]:
   with self.subTest(url=url),self.assertRaises(ValueError):self.configure(webhook=url)
  self.configure(secret='private-signing-secret')
  self.assertTrue(self.settings().get(self.studio)['effective']['has_secret'])
  self.assertNotIn('private-signing-secret',json.dumps(self.settings().get(self.studio)))
 def test_transactional_enqueue_deduplicates_without_network(self):
  self.configure();self.queue();self.queue()
  from server.core.notifications import NotificationQueue,enqueue
  q=NotificationQueue(self.store)
  self.assertEqual(len(q.listing(self.studio,self.project)),1)
  with self.assertRaises(RuntimeError):
   with self.store.connection() as db:
    enqueue(self.store,db,self.project,'testing:1','fixture:rollback','failed',{})
    raise RuntimeError('rollback')
  self.assertEqual(len(q.listing(self.studio,self.project)),1)
 def test_success_timeout_business_failure_and_recovery_are_distinct(self):
  self.configure();self.queue()
  from server.core.notifications import NotificationQueue
  from server.connectors.feishu_webhook import DeliveryUnknown,DeliveryRejected
  q=NotificationQueue(self.store)
  with patch('server.core.notifications.send_card',return_value=None) as send:
   self.assertTrue(q.run_once());send.assert_called_once()
  first=q.listing(self.studio,self.project)[0];self.assertEqual(first['status'],'sent')
  q.resend(self.studio,self.project,first['id'])
  with patch('server.core.notifications.send_card',side_effect=DeliveryUnknown('网络响应不确定')):q.run_once()
  self.assertEqual(q.listing(self.studio,self.project)[0]['status'],'unknown');self.assertFalse(q.run_once())
  q.resend(self.studio,self.project,first['id'])
  with patch('server.core.notifications.send_card',side_effect=DeliveryRejected('飞书拒绝')):q.run_once()
  self.assertEqual(q.listing(self.studio,self.project)[0]['status'],'failed')
  q.resend(self.studio,self.project,first['id']);q.claim();q.recover()
  self.assertEqual(q.listing(self.studio,self.project)[0]['status'],'unknown')
 def test_disabled_and_changed_targets_do_not_receive_queued_data(self):
  self.configure();self.queue();self.configure(webhook=HOOK[:-1]+'2')
  from server.core.notifications import NotificationQueue
  q=NotificationQueue(self.store)
  with patch('server.core.notifications.send_card') as send:q.run_once();send.assert_not_called()
  self.assertEqual(q.listing(self.studio,self.project)[0]['status'],'cancelled')
 def test_card_has_real_counts_and_does_not_echo_raw_content_or_secrets(self):
  self.configure()
  from server.core.notifications import enqueue,NotificationQueue
  with self.store.connection() as db:
   enqueue(self.store,db,self.project,'testing:1','fixture:counts','completed',{'method':'static_code_review','results':[{'status':'failed','detail':HOOK},{'status':'passed'}]},origin='agent')
  with patch('server.core.notifications.send_card') as send:NotificationQueue(self.store).run_once()
  card=send.call_args.args[1];raw=json.dumps(card,ensure_ascii=False)
  self.assertIn('静态',raw);self.assertIn('2',raw);self.assertNotIn(HOOK,raw);self.assertNotIn('99%',raw)
 def test_connection_card_returns_to_settings_without_fake_node(self):
  self.configure(public_url='http://192.168.1.50:8766')
  from server.core.notifications import NotificationQueue
  q=NotificationQueue(self.store);q.test(self.studio)
  with patch('server.core.notifications.send_card') as send:q.run_once()
  from urllib.parse import urlsplit,parse_qs
  link=send.call_args.args[1]['elements'][1]['actions'][0]['url'];query=parse_qs(urlsplit(link).query)
  self.assertEqual(query.get('view'),['settings']);self.assertNotIn('node',query)
 def test_failure_does_not_claim_result_saved_or_waiting_review(self):
  self.configure()
  from server.core.notifications import enqueue,NotificationQueue
  with self.store.connection() as db:enqueue(self.store,db,self.project,'testing:0','failed-fixture','failed')
  with patch('server.core.notifications.send_card') as send:NotificationQueue(self.store).run_once()
  raw=json.dumps(send.call_args.args[1],ensure_ascii=False)
  self.assertNotIn('结果已保存',raw);self.assertNotIn('等待人工审核',raw)
 def test_node_scope_is_normalized_and_test_uses_exact_scope(self):
  self.configure()
  self.settings().save(self.studio,self.project,{'enabled':False},node='product:0')
  self.assertFalse(self.settings().effective(self.studio,self.project,'product','product:0')['enabled'])
  from server.core.notifications import NotificationQueue
  self.settings().save(self.studio,self.project,{'enabled':False},'product','product:0')
  q=NotificationQueue(self.store)
  q.test(self.studio,self.project,'product')
  with patch('server.core.notifications.send_card') as send:q.run_once();send.assert_called_once()
 def test_archived_project_never_receives_queued_results(self):
  self.configure();self.queue()
  with self.store.connection() as db:db.execute('UPDATE projects SET archived=1 WHERE id=?',(self.project,))
  from server.core.notifications import NotificationQueue
  with patch('server.core.notifications.send_card') as send:NotificationQueue(self.store).run_once();send.assert_not_called()
 def test_corrupt_config_cannot_prevent_result_save(self):
  self.settings().path.write_text(json.dumps({'rules':{self.settings().key(self.studio):{'webhook':123,'enabled':True}}}))
  self.queue()
  with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM node_notifications').fetchone()[0],0)

class WebhookProtocolTests(unittest.TestCase):
 def test_signing_and_business_response_validation(self):
  from server.connectors.feishu_webhook import signing,send_card,DeliveryRejected,DeliveryUnknown
  import hmac,hashlib,base64
  expected=base64.b64encode(hmac.new(('123'+chr(10)+'secret').encode(),b'',hashlib.sha256).digest()).decode()
  self.assertEqual(signing('secret','123'),expected)
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,*args):return b'{"code":0}'
  with patch('server.connectors.feishu_webhook.urlopen',return_value=Response()) as request:
   send_card({'webhook':HOOK,'secret':'secret'},{'header':{}})
   payload=json.loads(request.call_args.args[0].data);self.assertEqual(payload['msg_type'],'interactive');self.assertIn('sign',payload)
  class Rejected(Response):
   def read(self,*args):return b'{"code":19024,"msg":"private details"}'
  with patch('server.connectors.feishu_webhook.urlopen',return_value=Rejected()),self.assertRaises(DeliveryRejected):send_card({'webhook':HOOK},{})
  with patch('server.connectors.feishu_webhook.urlopen',side_effect=TimeoutError()),self.assertRaises(DeliveryUnknown):send_card({'webhook':HOOK},{})
