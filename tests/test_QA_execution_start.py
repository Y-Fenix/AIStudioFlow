"""Atomic baseline refresh: real Store, supplied inspected baseline, no target Git writes."""
import tempfile
import unittest
from unittest.mock import patch
from server.store import Store


class QA_ExecutionStartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.s=Store(self.temp.name+'/db.sqlite');self.p=self.s.create_project('静态启动')['id']
        self.t=self.s.create_task(self.p,'case');self.t=self.s.record_artifact(self.p,self.t['id'],0,{'legacy_fixture':True})
        self.old={'repository':'/fixture','project_root':'/fixture/GagaSort','branch':'master','commit':'old','code_fingerprint':'old','execution_suite':'static'}
        self.t=self.s.bind_execution(self.p,self.t['id'],self.old,self.t['revision']);self.t=self.s.decide(self.p,self.t['id'],'confirm',self.t['revision'])
        self.new={**self.old,'commit':'new','code_fingerprint':'new'}

    def start(self,binding=None,revision=None):
        self.assertTrue(hasattr(self.s,'start_static_review'),'missing atomic static start')
        return self.s.start_static_review(self.p,self.t['id'],binding or self.new,self.t['revision'] if revision is None else revision)

    def test_changed_baseline_updates_then_enqueues_at_new_revision(self):
        r=self.start();self.assertEqual(r['task']['binding'],self.new)
        self.assertEqual(r['job']['revision'],self.t['revision']+1);self.assertEqual(r['job']['kind'],'execute')
        self.assertIn('0',r['task']['artifacts'])

    def test_same_baseline_reuses_revision_and_existing_job_without_duplicate(self):
        r=self.start(self.old);self.assertEqual(r['task']['revision'],self.t['revision'])
        again=self.start(self.old);self.assertEqual(again['job']['id'],r['job']['id'])

    def test_stale_revision_and_different_branch_cannot_rebind(self):
        with self.assertRaisesRegex(ValueError,'更新|变化'):self.start(revision=0)
        with self.assertRaisesRegex(ValueError,'分支|目录'):self.start({**self.new,'branch':'release'})
        self.assertEqual(self.s.task(self.p,self.t['id'])['binding'],self.old)

    def test_enqueue_failure_rolls_back_refresh_and_active_job_is_not_invalidated(self):
        with patch.object(self.s,'enqueue_operation',side_effect=ValueError('enqueue failed')):
            with self.assertRaisesRegex(ValueError,'enqueue failed'):self.start()
        self.assertEqual(self.s.task(self.p,self.t['id'])['binding'],self.old)
        first=self.start(self.old)
        with self.assertRaisesRegex(ValueError,'后台|进行'):self.start()
        self.assertEqual(self.s.task(self.p,self.t['id'])['binding'],self.old)
        self.assertEqual(self.s.task(self.p,self.t['id'])['jobs'][0]['id'],first['job']['id'])

    def test_new_start_requires_edit_and_execute_permissions_and_registered_path(self):
        from server.core.gateway import Gateway
        gateway=Gateway(self.s)
        original=gateway.policy.require
        calls=[]
        def require(resource,action,**scope):
            calls.append((resource,action,scope.get('node')))
            return original(resource,action,**scope)
        with patch.object(gateway.policy,'require',side_effect=require):
            gateway.authorize(['api','studios',self.s.studios()[0]['id'],'projects',self.p,'tasks',self.t['id'],'start-static-review'],'',{'revision':self.t['revision']},True)
        self.assertIn(('node','edit','testing:1'),calls);self.assertIn(('node','execute','testing:1'),calls)
