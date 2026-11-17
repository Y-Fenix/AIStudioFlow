"""Local worker errors need a private traceback rather than silent generic failures."""
import threading
import unittest
from unittest.mock import patch

from server.jobs import GenerationWorker


class QA_JobDiagnosticsTests(unittest.TestCase):
    def test_local_permission_and_internal_errors_keep_traceback_in_server_log(self):
        for failure in (PermissionError(1, 'Operation not permitted'), RuntimeError('internal failure')):
            with self.subTest(failure=type(failure).__name__):
                finished = threading.Event()
                job = {'id': 'diagnostic-job', 'actor': 'local'}
                class QA_Store:
                    error = None
                    claimed = False
                    lock = threading.Lock()
                    def recover_generations(self): pass
                    def claim_generation(self):
                        with self.lock:
                            if self.claimed:return None
                            self.claimed=True
                            return job
                    def finish_generation(self, _, error=None):
                        self.error = error
                        finished.set()
                store = QA_Store()
                with patch('server.jobs.authorize_testing_job', side_effect=failure), self.assertLogs(
                        'server.jobs', level='ERROR') as logs:
                    worker = GenerationWorker(store)
                    try:
                        self.assertTrue(finished.wait(2))
                    finally:
                        worker.close()
                self.assertIn('diagnostic-job', logs.output[0])
                self.assertIsNotNone(logs.records[0].exc_info)
                self.assertTrue(store.error)

