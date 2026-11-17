import json
import unittest
from unittest.mock import Mock


class JobTelemetryTests(unittest.TestCase):
    def test_batch_and_phase_changes_clear_request_diagnostics_but_keep_job_progress(self):
        from server.core.job_telemetry import JobTelemetry
        for update in ({'batch': 2, 'phase': 'design'}, {'batch': 1, 'phase': 'audit'}):
            with self.subTest(update=update):
                store = Mock()
                telemetry = JobTelemetry(store, {}, {'source': 'relay', 'model': 'm'})
                telemetry.publish({'batch': 1, 'phase': 'design', 'completed': 3, 'batches': 69,
                    'state': 'completed', 'events_received': 3000, 'elapsed_seconds': 120,
                    'output_bytes': 8000, 'attempt': 2, 'reason': 'old transport error',
                    'validation_attempt': 1, 'validation_error': 'old quote error'})
                telemetry.publish(update)
                value = store.operation_progress.call_args.args[1]
                for field in ('events_received', 'elapsed_seconds', 'output_bytes', 'attempt',
                              'reason', 'validation_attempt', 'validation_error'):
                    self.assertNotIn(field, value)
                self.assertEqual(value['completed'], 3)
                self.assertEqual(value['batches'], 69)
                self.assertEqual(value['requested_model'], 'm')
                self.assertEqual(value['state'], 'preparing')

    def test_progress_preserves_business_and_model_state_without_credentials(self):
        from server.core.job_telemetry import JobTelemetry
        store = Mock()
        telemetry = JobTelemetry(store, {'id': 'fixture'},
                                 {'source': 'custom', 'model': 'requested-model', 'effort': 'high',
                                  'api_key': 'private-key', 'base_url': 'https://secret.example?token=secret'})
        telemetry.publish({'completed': 1, 'total': 2, 'checkpoint_reused_count': 1})
        telemetry.publish({'state': 'running', 'events_received': 7})
        value = store.operation_progress.call_args.args[1]
        self.assertEqual(value['completed'], 1)
        self.assertEqual(value['checkpoint_reused_count'], 1)
        self.assertEqual(value['requested_model'], 'requested-model')
        self.assertEqual(value['model_source'], 'custom')
        self.assertEqual(value['events_received'], 7)
        self.assertGreater(value['progress_updated_at'], 0)
        self.assertNotIn('private-key', json.dumps(value))
        self.assertNotIn('secret.example', json.dumps(value))

    def test_new_case_clears_previous_model_response_state(self):
        from server.core.job_telemetry import JobTelemetry
        store = Mock()
        telemetry = JobTelemetry(store, {}, {'source': 'relay', 'model': 'm'})
        telemetry.publish({'case_id': 'C1', 'state': 'completed', 'elapsed_seconds': 100, 'events_received': 9,
                           'timeout_kind': 'inactivity', 'idle_timeout_seconds': 600})
        telemetry.publish({'case_id': 'C2', 'completed': 1, 'total': 2})
        value = store.operation_progress.call_args.args[1]
        self.assertNotIn('events_received', value)
        self.assertNotIn('elapsed_seconds', value)
        self.assertNotIn('timeout_kind', value)
        self.assertEqual(value['state'], 'preparing')
