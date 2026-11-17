"""Delegated decisions use actual validators/SQLite; model and Git boundaries are fixtures."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server.store import Store
from server.static_review import execute_static
from server.core.identity import current_user


class QA_AutomationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('server.core.testing_automation'),'missing delegated automation service')
        from server.core.testing_automation import TestingAutomation
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        self.s=Store(root/'db.sqlite');self.studio=self.s.studios()[0]['id'];self.p=self.s.create_project('自动')['id']
        self.t=self.s.create_task(self.p,'审核到内部草稿');self.t=self.s.import_requirement(self.p,self.t['id'],'req','奖励只能领取一次')
        req=self.t['requirements'][0]
        output={'points':[{'id':'P','title':'重复领取','requirement_id':req['id'],'quote':req['content']}],
            'cases':[{'id':'C','title':'重复领取','point_ids':['P'],'preconditions':['已领取'], 'steps':[{'action':'再次领取','expected':'金币不增加'}]}],
            'gaps':[],'ambiguities':['缺少远端奖励服务资料']}
        self.t=self.s.record_artifact(self.p,self.t['id'],0,output)
        source=root/'GagaSort/Assets/Reward.cs';source.parent.mkdir(parents=True);source.write_text('class Reward { void Claim() { coins += 10; } }\n')
        self.source=source
        self.binding={'repository':str(root),'project_root':str(root/'GagaSort'),'branch':'master','commit':'sha','code_fingerprint':'hash','execution_suite':'static'}
        self.t=self.s.bind_execution(self.p,self.t['id'],self.binding,self.t['revision'])
        self.a=TestingAutomation(self.s)
        self.baseline=patch('server.gagasort.inspect_project',return_value=self.binding);self.baseline.start();self.addCleanup(self.baseline.stop)

    def enable(self):
        t=self.s.task(self.p,self.t['id']);return self.a.save(self.p,t['id'],{'enabled':True,'revision':t['revision'],'config_revision':self.a.get(self.p,t['id'])['revision']})

    def steps(self,n=1):
        for _ in range(n):self.a.run_once()
        return self.s.task(self.p,self.t['id'])

    def finish_execution(self):
        job=self.s.claim_generation();self.assertEqual(job['kind'],'execute')
        content=self.source.read_text()
        class Client:
            def request_json(_,prompt):
                if '"sources": {}' in prompt:return {'read':['Assets/Reward.cs']}
                return {'assertions':[{'step_index':0,'status':'failed','reasoning':'再次进入Claim仍直接增加金币','precondition_analysis':'已领取仍可再次调用入口','counterexample_search':'检查Claim的重复调用守卫',
                    'call_chain':[{'file':'Assets/Reward.cs','line':1,'quote':content}],
                    'counterexample':{'preconditions':['已领取'],'steps':['再次调用Claim'],'expected':'金币不增加','actual':'金币增加10','reachability':'入口没有已领取条件守卫'}}]}
        result=execute_static(self.binding,self.t['artifacts']['0']['cases'],self.t['requirements'],Path(self.temp.name)/'evidence',client=Client())
        self.s.finish_generation(job,artifact=result)

    def finish_attribution(self,analysed=True):
        job=self.s.claim_generation();self.assertEqual(job['kind'],'attribution')
        suggestions=[{'id':'R','title':'领取入口缺少幂等守卫','reasoning':'同一入口直接加金币','result_ids':['C'],'evidence':[{'file':'Assets/Reward.cs','line':1,'quote':self.source.read_text()}],'confirmed':False}] if analysed else []
        self.s.finish_generation(job,artifact={'suggestions':suggestions,'unanalysed':[] if analysed else ['C']})

    def reach_attribution(self):
        self.enable();self.steps(3);self.finish_execution();self.steps(2);self.finish_attribution()

    def test_auto_scope_keeps_risks_and_chain_stops_at_internal_draft_without_external_calls(self):
        self.reach_attribution();task=self.steps(8);state=self.a.get(self.p,task['id'])
        self.assertEqual(state['state'],'completed');self.assertFalse(state['enabled']);self.assertEqual(task['stage'],4)
        review=task['artifacts']['0']['user_review'];self.assertEqual(review['decision_origin'],'automation');self.assertIn('风险',review['scope'])
        self.assertEqual(len(review['decisions']),1);self.assertEqual(task['artifacts']['0']['ambiguities'],['缺少远端奖励服务资料'])
        drafts=task['artifacts']['4'];self.assertEqual(len(drafts['drafts']),1);self.assertFalse(drafts['publication_complete'])
        self.assertEqual(drafts['drafts'][0]['reproduction_provenance'],'static_inference');self.assertEqual(drafts['drafts'][0]['missing'],[])
        self.assertEqual(task['status'],'waiting_user');self.assertTrue(any('自动决策' in e['detail'] for e in task['events']))

    def test_unanalysed_failures_pause_without_faking_root_or_passing(self):
        self.enable();self.steps(3);self.finish_execution();self.steps(2);self.finish_attribution(False);self.steps(2)
        state=self.a.get(self.p,self.t['id']);self.assertEqual(state['state'],'paused');self.assertIn('归因',state['detail'])
        self.assertNotIn('4',self.s.task(self.p,self.t['id'])['artifacts'])

    def test_stop_and_restart_do_not_confirm_or_enqueue_more_work(self):
        self.enable();state=self.a.get(self.p,self.t['id']);self.a.save(self.p,self.t['id'],{'enabled':False,'revision':self.t['revision'],'config_revision':state['revision']})
        self.steps(2);self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],0)
        self.enable();self.a.recover();self.steps(2);self.assertEqual(self.a.get(self.p,self.t['id'])['state'],'paused')
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],0)

    def test_permission_revocation_and_user_edit_pause_instead_of_bypassing_gates(self):
        self.enable()
        with patch('server.core.testing_automation.Policy.require',side_effect=PermissionError('撤回权限')):self.steps()
        self.assertEqual(self.a.get(self.p,self.t['id'])['state'],'paused')
        self.enable();self.s.import_requirement(self.p,self.t['id'],'req','新规则');self.steps()
        self.assertEqual(self.a.get(self.p,self.t['id'])['state'],'paused')

    def test_failed_job_is_not_retried_forever_and_waiting_polls_do_not_duplicate_jobs(self):
        self.enable();self.steps(8)
        task=self.s.task(self.p,self.t['id']);self.assertEqual(len(task['jobs']),1)
        job=self.s.claim_generation();self.s.finish_generation(job,error='服务不可用');self.steps(4)
        self.assertEqual(len(self.s.task(self.p,self.t['id'])['jobs']),1);self.assertEqual(self.a.get(self.p,self.t['id'])['state'],'paused')

    def test_existing_user_request_for_revision_is_not_silently_accepted(self):
        from server.requirements import review_cases
        t=self.s.task(self.p,self.t['id']);o=t['artifacts']['0'];items=t['case_review_items']
        r=review_cases(o,t['requirements'],[{'id':x['id'],'action':'needs_revision','reason':'必须先补资料'} for x in items],True)
        self.s.record_artifact(self.p,t['id'],0,{**o,'user_review':r},expected_revision=t['revision']);self.enable();self.steps(2)
        self.assertEqual(self.a.get(self.p,t['id'])['state'],'paused');self.assertEqual(self.s.task(self.p,t['id'])['stage'],0)

    def test_real_source_drift_before_auto_root_confirmation_pauses(self):
        self.reach_attribution();self.source.write_text('class Reward { void Claim() { return; } }\n');self.steps(2)
        self.assertEqual(self.a.get(self.p,self.t['id'])['state'],'paused')
        self.assertNotIn('2',self.s.task(self.p,self.t['id'])['artifacts'])

    def test_original_auto_continue_does_not_duplicate_autopilot_jobs(self):
        from server.core.node_continuation import NodeContinuation
        c=NodeContinuation(self.s);settings=c.get(self.studio,self.p,'testing');edge=settings['edges'][0]
        c.save(self.studio,self.p,'testing',{'revision':settings['revision'],'source':edge['source'],'target':edge['target'],'enabled':True})
        self.enable();self.steps(3);c.run_once()
        with self.s.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE task_id=?",(self.t['id'],)).fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM node_continuation_events WHERE task_id=?',(self.t['id'],)).fetchone()[0],0)

    def test_auto_generation_with_no_artifact_enqueues_once_and_skill_change_pauses(self):
        t=self.s.reset_node(self.p,self.t['id'],0,self.t['revision'],'重新生成',True);self.enable();self.steps(3)
        jobs=self.s.task(self.p,t['id'])['jobs'];self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['kind'],'generate')
        self.s.import_requirement(self.p,t['id'],'new','额外规则');self.steps(2)
        self.assertEqual(self.a.get(self.p,t['id'])['state'],'paused')

    def test_stop_remains_effective_with_stale_ui_revision(self):
        self.enable();old=self.a.get(self.p,self.t['id']);self.steps()
        self.a.save(self.p,self.t['id'],{'enabled':False,'revision':self.t['revision'],'config_revision':old['revision']})
        self.steps(3);self.assertFalse(self.a.get(self.p,self.t['id'])['enabled'])
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],0)

    def test_existing_accepted_root_does_not_bypass_new_code_check(self):
        self.reach_attribution();self.steps()
        with patch('server.gagasort.inspect_project',return_value={**self.binding,'commit':'changed'}):self.steps(2)
        self.assertEqual(self.a.get(self.p,self.t['id'])['state'],'paused')
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],2)

    def test_hidden_node_automation_errors_are_not_exposed_to_filing_only_viewer(self):
        from server.core.gateway import Gateway
        t=self.s.task(self.p,self.t['id']);t['automation']={**t['automation'],'detail':'private-source-url'}
        g=Gateway(self.s)
        with patch.object(g.policy,'visible_nodes',return_value=['testing:4']),patch.object(g.policy,'allowed',return_value=False),patch('server.core.testing_automation.TestingAutomation.can_manage',return_value=False):
            visible=g.filter_response(t,{'studio':self.studio,'project':self.p,'testing':True})
        self.assertNotIn('private-source-url',visible['automation']['detail'])
