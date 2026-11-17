"""Merge job progress without changing task revisions or storing model credentials."""
import threading
import time


class JobTelemetry:
    def __init__(self, store, job, selection):
        self.store, self.job = store, job
        self.lock = threading.RLock()
        self.value = {'requested_model': selection.get('model', ''), 'effort': selection.get('effort'),
                      'model_source': selection.get('source', 'relay'), 'started_at': time.time(),
                      'state': 'preparing'}

    def publish(self, update):
        with self.lock:
            # A different case, batch or phase must not inherit another request's diagnostics.
            changed_case = update.get('case_id') and update['case_id'] != self.value.get('case_id')
            changed_batch = 'batch' in update and (update['batch'], update.get('phase')) != (
                self.value.get('batch'), self.value.get('phase'))
            if changed_case or changed_batch:
                for key in ('elapsed_seconds', 'events_received', 'assistant_chars', 'last_event',
                            'seconds_since_response', 'progress_events', 'upstream_error_kind',
                            'upstream_error_code', 'reason', 'attempt', 'max_attempts',
                            'timeout_kind', 'idle_timeout_seconds', 'transport', 'input_chars',
                            'output_bytes', 'validation_attempt', 'validation_max_attempts',
                            'validation_error', 'checkpoint_reused'):
                    self.value.pop(key, None)
                self.value['state'] = 'preparing'
            self.value.update(update)
            self.value['progress_updated_at'] = time.time()
            self.store.operation_progress(self.job, dict(self.value))
