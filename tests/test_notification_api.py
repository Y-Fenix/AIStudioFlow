import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from server.app import create_server
from server.store import Store
from tests.test_notifications import HOOK

class NotificationApiTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name)/'api.sqlite'
  transport=patch('server.core.notifications.send_card',return_value=None);transport.start();self.addCleanup(transport.stop)
  self.server=create_server('127.0.0.1',0,self.path,local_development=True)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.store=Store(self.path);self.studio=self.store.studios()[0]['id'];self.project=self.store.create_project('HTTP 通知')['id']
  self.root='/api/studios/'+self.studio+'/notifications'
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def request(self,path,body=None,cookie=None):
  headers={'Content-Type':'application/json'}
  if cookie:headers['Cookie']='studioflow_session='+cookie
  req=Request('http://127.0.0.1:'+str(self.server.server_port)+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
  try:response=urlopen(req)
  except HTTPError as exc:response=exc
  with response:return response.status,json.load(response)
 def test_save_get_test_and_cross_scope(self):
  status,value=self.request(self.root,{'enabled':True,'webhook':HOOK})
  self.assertEqual(status,200,value);self.assertNotIn(HOOK,json.dumps(value))
  status,value=self.request(self.root+'?project='+self.project)
  self.assertEqual(status,200);self.assertTrue(value['effective']['enabled'])
  with patch('server.core.notifications.send_card'):
   status,value=self.request(self.root+'/test?project='+self.project,{})
   self.assertEqual(status,200,value);self.assertIsInstance(value['id'],int)
  status,value=self.request(self.root+'/history?project='+self.project)
  self.assertEqual(status,200,value);self.assertEqual(len(value['items']),1)
  self.assertEqual(self.request(self.root+'?project=missing')[0],404)
 def test_member_cannot_read_config_or_send_or_list(self):
  import hashlib,time
  with self.store.connection() as db:
   db.execute("INSERT INTO users(id,tenant_key,open_id,name,status) VALUES('member','fixture','m','成员','active')")
   db.execute("INSERT INTO studio_memberships(studio_id,user_id,role) VALUES(?,'member','member')",(self.studio,))
   db.execute("INSERT INTO auth_sessions(token_hash,user_id,expires) VALUES(?,'member',?)",(hashlib.sha256(b'member-cookie').hexdigest(),time.time()+1000))
  for suffix,body in [('',None),('',{'enabled':True,'webhook':HOOK}),('/test',{}),('/history',None)]:
   self.assertEqual(self.request(self.root+suffix,body,'member-cookie')[0],403)
