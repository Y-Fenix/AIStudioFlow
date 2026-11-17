import tempfile
import unittest
from pathlib import Path
from server.store import Store
from server.core.notification_settings import NotificationSettings
from server.core.notifications import NotificationQueue
from server.studio_workspaces import Workspaces
from server.department_jobs import DepartmentExecutionQueue
from server.core.integrations import AdapterRegistry
from tests.test_notifications import HOOK

class NotificationEventTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=Store(Path(self.temp.name)/'events.sqlite');self.studio=self.store.studios()[0]['id']
  self.project=self.store.create_project('事件样例')['id'];self.task=self.store.create_task(self.project,'批次')['id']
  NotificationSettings(self.store).save(self.studio,'',{'enabled':True,'webhook':HOOK})
 def rows(self):return NotificationQueue(self.store).listing(self.studio,self.project)
 def test_generated_result_notifies_once_after_commit(self):
  self.store.import_requirement(self.project,self.task,'需求','音量保存')
  self.store.enqueue_generation(self.project,self.task);job=self.store.claim_generation()
  self.store.finish_generation(job,{'cases':[]})
  self.assertEqual([x['event'] for x in self.rows()],['completed'])
  self.assertEqual(self.rows()[0]['task_id'],self.task)
 def test_large_result_commits_notification_without_nested_database_reader(self):
  import sqlite3
  from unittest.mock import patch
  self.store.import_requirement(self.project,self.task,'需求','音量保存')
  self.store.enqueue_generation(self.project,self.task);job=self.store.claim_generation()
  connect=sqlite3.connect
  def fast_connect(*args,**kwargs):
   kwargs['timeout']=.1
   return connect(*args,**kwargs)
  artifact={'cases':[],'detail':'large-result-'*400000}
  with patch('server.store.sqlite3.connect',side_effect=fast_connect):
   self.store.finish_generation(job,artifact)
  task=self.store.task(self.project,self.task)
  self.assertEqual(task['artifacts']['0']['detail'],artifact['detail'])
  self.assertEqual(task['jobs'][0]['status'],'completed')
  self.assertEqual([row['event'] for row in self.rows()],['completed'])
 def test_discarded_result_does_not_claim_success(self):
  self.store.import_requirement(self.project,self.task,'需求','音量保存')
  self.store.enqueue_generation(self.project,self.task);job=self.store.claim_generation()
  self.store.import_requirement(self.project,self.task,'需求','语言保存')
  self.store.finish_generation(job,{'cases':[]});self.assertEqual(self.rows(),[])
 def test_job_failure_and_restart_notify(self):
  self.store.import_requirement(self.project,self.task,'需求','音量保存')
  self.store.enqueue_generation(self.project,self.task);job=self.store.claim_generation()
  self.store.finish_generation(job,error='fixture failure');self.assertEqual(self.rows()[0]['event'],'failed')
  self.store.enqueue_generation(self.project,self.task);self.store.claim_generation();self.store.recover_generations()
  self.assertEqual(self.rows()[0]['event'],'interrupted')
 def test_all_six_artifact_stages_are_supported_without_renaming_node_ids(self):
  for stage in range(6):
   with self.store.connection() as db:db.execute('UPDATE tasks SET stage=? WHERE id=?',(stage,self.task))
   self.store.record_artifact(self.project,self.task,stage,{'fixture':'协议样例'})
  self.assertEqual({r['node'] for r in self.rows()},{'testing:'+str(i) for i in range(6)})
 def test_manual_deliverable_not_every_input_save_notifies(self):
  w=Workspaces(self.store)
  a=w.save(self.studio,self.project,'product:0',{'revision':0,'inputs':'输入'})
  self.assertEqual(self.rows(),[])
  a=w.save(self.studio,self.project,'product:0',{'revision':a['revision'],'deliverable':'人工交付物'})
  self.assertEqual(self.rows()[0]['event'],'manual')
  w.save(self.studio,self.project,'product:0',{'revision':a['revision'],'inputs':'改输入'})
  self.assertEqual(len(self.rows()),1)
 def test_department_adapter_completion_and_failure(self):
  registry=AdapterRegistry()
  class Adapter:
   def execute(self,ctx):return {'deliverable':'协议样例，非真实调研'}
  registry.register('product',Adapter());q=DepartmentExecutionQueue(self.store,registry)
  q.enqueue(self.studio,self.project,'product:0',0);q.run_once()
  self.assertEqual([r['event'] for r in self.rows()],['completed'])
  registry2=AdapterRegistry()
  class Broken:
   def execute(self,ctx):raise ValueError('fixture failure')
  registry2.register('product',Broken());q2=DepartmentExecutionQueue(self.store,registry2)
  revision=Workspaces(self.store).get(self.studio,self.project,'product:0')['revision']
  q2.enqueue(self.studio,self.project,'product:0',revision);q2.run_once()
  self.assertEqual([r['event'] for r in self.rows()],['failed','completed'])
 def test_regression_started_at_filing_belongs_to_regression_node(self):
  with self.store.connection() as db:
   db.execute("UPDATE tasks SET stage=4,revision=0 WHERE id=?",(self.task,))
   db.execute("INSERT INTO jobs(id,project_id,task_id,revision,status,stage,kind) VALUES('regression-fixture',?,?,0,'running',4,'regression')",(self.project,self.task))
  job={'id':'regression-fixture','project_id':self.project,'task_id':self.task,'stage':4,'kind':'regression','revision':0}
  self.store.finish_generation(job,{'roots':[]})
  self.assertEqual(self.rows()[0]['node'],'testing:5')
 def test_sync_attribution_and_regression_are_not_silent(self):
  with self.store.connection() as db:db.execute('UPDATE tasks SET stage=2,revision=0 WHERE id=?',(self.task,))
  self.store.save_attribution(self.project,self.task,{'suggestions':[]},0)
  with self.store.connection() as db:db.execute('UPDATE tasks SET stage=4 WHERE id=?',(self.task,))
  self.store.save_logic_regression(self.project,self.task,{'roots':[]},1)
  self.assertEqual({r['node'] for r in self.rows()},{'testing:2','testing:5'})
 def test_actual_bug_publication_notifies_and_unknown_is_not_success(self):
  from server.publication import PublicationLedger
  ledger=PublicationLedger(self.store)
  with self.store.connection() as db:
   db.execute("INSERT INTO publications(identity,task_id,root_cause_id,request_hash,request,status,attempt) VALUES('publication-fixture',?,'root','hash','{}','sending','attempt')",(self.task,))
  ledger.finish('publication-fixture','attempt',{'record_id_list':['recFixture']})
  self.assertEqual(self.rows()[0]['event'],'completed');self.assertEqual(self.rows()[0]['node'],'testing:4')
  with self.store.connection() as db:
   db.execute("INSERT INTO publications(identity,task_id,root_cause_id,request_hash,request,status,attempt) VALUES('uncertain-fixture',?,'root2','hash2','{}','sending','attempt2')",(self.task,))
  ledger.finish('uncertain-fixture','attempt2')
  self.assertEqual(self.rows()[0]['event'],'failed')
