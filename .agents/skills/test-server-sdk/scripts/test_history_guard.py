import importlib.util
import unittest
from pathlib import Path


class HistoryGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'history_guard', Path(__file__).with_name('history_guard.py'))
        cls.guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.guard)

    def previous(self):
        return {'old/findings.json': {'assertions': [
            {'id': 'PAY-1', 'status': 'issue'},
            {'id': 'BI-2', 'status': 'risk'}]}}

    def row(self, old_id, state='pending_review', **extra):
        return dict(source_report='old/findings.json', source_id=old_id,
                    disposition=state, **extra)

    def test_missing_old_issue_is_rejected(self):
        errors = self.guard.validate({'assertions': [], 'history_tracking': []}, self.previous())
        self.assertEqual(len(errors), 2)

    def test_unreviewed_items_are_retained_without_claiming_confirmation(self):
        report = {'assertions': [], 'history_tracking': [
            self.row('PAY-1'), self.row('BI-2')]}
        self.assertEqual(self.guard.validate(report, self.previous()), [])

    def test_closed_issue_requires_reason_and_evidence(self):
        report = {'assertions': [], 'history_tracking': [
            self.row('PAY-1', 'fixed'), self.row('BI-2')]}
        self.assertTrue(self.guard.validate(report, self.previous()))
        report['history_tracking'][0].update(reason='Repair verified in isolated test',
                                             evidence=['tests/result.txt'])
        self.assertEqual(self.guard.validate(report, self.previous()), [])

    def test_mapping_requires_current_assertion_and_downgrade_evidence(self):
        report = {'assertions': [{'id': 'NEW-1', 'status': 'risk'}],
                  'history_tracking': [self.row('PAY-1', 'confirmed', current_id='NEW-1'),
                                       self.row('BI-2')]}
        self.assertTrue(self.guard.validate(report, self.previous()))
        report['history_tracking'][0].update(reason='Downstream guard found', evidence=['source.kt:20'])
        self.assertEqual(self.guard.validate(report, self.previous()), [])
        report['history_tracking'][0]['current_id'] = 'MISSING'
        self.assertTrue(self.guard.validate(report, self.previous()))

    def test_pending_items_survive_multiple_runs(self):
        first = {'assertions': [], 'history_tracking': [self.row('PAY-1'), self.row('BI-2')]}
        second = {'assertions': [], 'history_tracking': []}
        self.assertEqual(len(self.guard.validate(second, {'next/findings.json': first})), 2)

    def test_duplicate_tracking_is_rejected(self):
        row = self.row('PAY-1')
        report = {'assertions': [], 'history_tracking': [row, row, self.row('BI-2')]}
        self.assertTrue(self.guard.validate(report, self.previous()))


if __name__ == '__main__':
    unittest.main()
