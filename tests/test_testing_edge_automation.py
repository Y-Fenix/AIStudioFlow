import unittest
from unittest.mock import patch
from tests.test_QA_automation import QA_AutomationTests

class TestingEdgeAutomationTests(QA_AutomationTests):
    # Reuse fixtures only; inherited tests remain useful full-auto regressions.
    def edge_service(self):
        from server.core.testing_edge_automation import TestingEdgeAutomation
        return TestingEdgeAutomation(self.s)

    def enable_edge(self, source='testing:0', target='testing:1'):
        from server.core.node_continuation import NodeContinuation
        service=NodeContinuation(self.s)
        config=service.get(self.studio,self.p,'testing')
        return service.save(self.studio,self.p,'testing',{'revision':config['revision'],'source':source,'target':target,'enabled':True})

    def finish_generation(self):
        output=self.s.task(self.p,self.t['id'])['artifacts']['0']
        self.s.enqueue_generation(self.p,self.t['id']);job=self.s.claim_generation()
        self.s.finish_generation(job,output)
        return job

    def test_enabled_edge_automatically_reviews_generated_scope_and_queues_target(self):
        self.enable_edge();job=self.finish_generation();service=self.edge_service()
        for _ in range(3):service.run_once()
        task=self.s.task(self.p,self.t['id'])
        self.assertEqual(task['stage'],1)
        self.assertEqual(task['artifacts']['0']['user_review']['decision_origin'],'automation')
        from server.core.node_continuation import NodeContinuation
        NodeContinuation(self.s).run_once()
        self.assertEqual(self.s.claim_generation()['kind'],'execute')
        self.assertFalse(self.a.get(self.p,task['id'])['enabled'])

    def test_disabled_edge_never_reviews_or_advances(self):
        self.finish_generation();service=self.edge_service()
        self.assertFalse(service.run_once())
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],0)

    def test_two_enabled_edges_reach_attribution_but_closed_edge_stops_there(self):
        from server.core.node_continuation import NodeContinuation
        self.enable_edge();self.enable_edge('testing:1','testing:2')
        self.finish_generation();service=self.edge_service()
        for _ in range(3):service.run_once()
        NodeContinuation(self.s).run_once();self.finish_execution()
        for _ in range(3):service.run_once()
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],2)
        NodeContinuation(self.s).run_once();self.finish_attribution()
        for _ in range(3):service.run_once()
        task=self.s.task(self.p,self.t['id'])
        self.assertEqual(task['stage'],2)
        self.assertNotIn('4',task['artifacts'])

    def test_global_automation_takes_precedence(self):
        self.enable_edge();self.enable();self.finish_generation()
        self.assertFalse(self.edge_service().run_once())

    def test_missing_binding_stops_with_specific_reason_without_fake_execute(self):
        self.enable_edge();self.finish_generation();service=self.edge_service()
        for _ in range(3):service.run_once()
        with self.s.connection() as db:db.execute("UPDATE tasks SET binding='{}' WHERE id=?",(self.t['id'],))
        from server.core.node_continuation import NodeContinuation
        NodeContinuation(self.s).run_once()
        with self.s.connection() as db:
            row=db.execute('SELECT status,detail FROM node_continuation_events WHERE task_id=?',(self.t['id'],)).fetchone()
            self.assertEqual(row['status'],'stopped');self.assertIn('绑定',row['detail'])

    def test_switch_off_after_completion_stops_pending_decisions(self):
        self.enable_edge();self.finish_generation()
        from server.core.node_continuation import NodeContinuation
        c=NodeContinuation(self.s);config=c.get(self.studio,self.p,'testing')
        c.save(self.studio,self.p,'testing',{'revision':config['revision'],'source':'testing:0','target':'testing:1','enabled':False})
        self.edge_service().run_once()
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],0)

    def test_user_edit_after_completion_invalidates_intent(self):
        self.enable_edge();self.finish_generation()
        task=self.s.task(self.p,self.t['id'])
        self.s.import_requirement(self.p,task['id'],'extra','新规则')
        self.edge_service().run_once()
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],0)

    def test_permission_revocation_prevents_automatic_decision(self):
        self.enable_edge();self.finish_generation()
        with patch('server.core.testing_edge_automation.Policy.require',side_effect=PermissionError('权限已撤回')):
            self.edge_service().run_once()
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],0)

    def test_completion_is_idempotent_and_restart_does_not_replay(self):
        from server.core.testing_edge_automation import record_completed
        self.enable_edge();job=self.finish_generation()
        task=self.s.task(self.p,self.t['id'])
        with self.s.connection() as db:
            record_completed(self.s,db,job,task['revision'])
            self.assertEqual(db.execute('SELECT count(*) FROM testing_edge_advances').fetchone()[0],1)
        service=self.edge_service();service.recover()
        self.assertFalse(service.run_once())
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],0)

    def test_user_needs_revision_is_not_overridden(self):
        from server.requirements import review_cases
        task=self.s.task(self.p,self.t['id']);o=task['artifacts']['0']
        review=review_cases(o,task['requirements'],[{'id':x['id'],'action':'needs_revision','reason':'先补资料'} for x in task['case_review_items']],True)
        self.s.record_artifact(self.p,task['id'],0,{**o,'user_review':review},expected_revision=task['revision'])
        self.enable_edge();self.finish_generation()
        for _ in range(3):self.edge_service().run_once()
        self.assertEqual(self.s.task(self.p,self.t['id'])['stage'],0)
