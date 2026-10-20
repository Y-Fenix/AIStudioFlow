import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from server.store import Store
from server.publication import PublicationLedger


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name+'/db.sqlite')
        self.project = self.store.create_project('fixture')['id']
        self.task = self.store.create_task(self.project, 'fixture')['id']
        with self.store.connection() as db:
            db.execute('UPDATE tasks SET stage=4 WHERE id=?', (self.task,))
        self.ledger = PublicationLedger(self.store)
        self.request = {'base_token':'base','table_id':'tbl','draft_key':'key',
                        'root_cause_id':'root','request_hash':'hash','payload':{'create_records':[{'description':'fixture'}]}}
        self.plan = {'requests':[self.request]}
        self.row = self.ledger.prepare(self.project,self.task,1,self.plan)[0]
        self.store.record_artifact(self.project,self.task,4,{'publication_plan':self.plan},1)

    def tearDown(self):
        self.temp.cleanup()

    def claim(self):
        return self.ledger.claim(self.project,self.task,self.row['identity'],'hash')

    def test_concurrent_clicks_only_one_claim_and_success_persists(self):
        def claim():
            try:return self.claim()
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:claim(), range(2)))
        claimed=[r for r in results if r]
        self.assertEqual(len(claimed),1)
        self.ledger.finish(self.row['identity'],claimed[0]['attempt'],{'record_id_list':['recFixture']})
        restarted=PublicationLedger(Store(self.store.path))
        restarted.recover_interrupted()
        self.assertEqual(restarted.list(self.project,self.task)[0]['status'],'published')
        with self.assertRaises(ValueError):self.claim()

    def test_interrupted_and_partial_responses_never_retry(self):
        attempt=self.claim()['attempt']
        self.ledger.finish(self.row['identity'],attempt,{'record_id_list':['recFixture'],'ignored_fields':['description']})
        self.assertEqual(self.ledger.list(self.project,self.task)[0]['status'],'uncertain')
        self.assertEqual(self.ledger.list(self.project,self.task)[0]['record_id'],'recFixture')
        with self.assertRaises(ValueError):self.claim()

    def test_restart_marks_sending_uncertain(self):
        self.claim()
        self.ledger.recover_interrupted()
        self.assertEqual(self.ledger.list(self.project,self.task)[0]['status'],'uncertain')
        with self.assertRaises(ValueError):self.claim()
        with self.assertRaises(ValueError):
            self.ledger.prepare(self.project,self.task,2,{'requests':[{**self.request,'request_hash':'changed'}]})

    def test_reconcile_requires_exact_fresh_check_and_does_not_claim_creation(self):
        from datetime import datetime, timezone
        attempt=self.claim()['attempt']
        self.ledger.finish(self.row['identity'],attempt)
        check={'record_id':'recFixture','base_token':'base','table_id':'tbl','request_hash':'hash',
               'matched':True,'mismatched_field_ids':[],'checked_at':datetime.now(timezone.utc).isoformat()}
        for invalid in [{**check,'matched':False},{**check,'request_hash':'other'},
                        {**check,'table_id':'other'},{**check,'checked_at':'2000-01-01T00:00:00+00:00'}]:
            with self.assertRaises(ValueError):self.ledger.reconcile(self.project,self.task,self.row['identity'],invalid,2)
        self.ledger.reconcile(self.project,self.task,self.row['identity'],check,2)
        row=self.ledger.list(self.project,self.task)[0]
        self.assertEqual(row['status'],'reconciled')
        self.assertEqual(row['record_id'],'recFixture')
        with self.assertRaises(ValueError):self.claim()
