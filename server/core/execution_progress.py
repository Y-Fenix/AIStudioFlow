"""Allowlisted, durable diagnostics; never alter business revisions or results."""
import json
import math
import re
import time


class ExecutionProgress:
    def __init__(self, store, table, identity, selection=None, *, revision=None, cursor=None):
        if table not in ('department_jobs', 'block_runs'):
            raise ValueError('unsupported progress scope')
        self.store, self.table, self.identity = store, table, identity
        self.revision = revision
        self.value = {'state': 'preparing', 'started_at': time.time()}
        if cursor is not None:
            self.value['cursor'] = cursor
        selection = selection or {}
        model = selection.get('model')
        if isinstance(model, str) and re.fullmatch(r'[\w.:-]{1,150}', model):
            self.value['requested_model'] = model
        if selection.get('effort') in ('low', 'medium', 'high', 'xhigh'):
            self.value['effort'] = selection['effort']
        if selection.get('source') in ('relay', 'custom'):
            self.value['model_source'] = selection['source']

    def publish(self, update):
        if not isinstance(update, dict):
            return
        numeric = ('elapsed_seconds', 'events_received', 'assistant_chars',
                   'seconds_since_response', 'idle_timeout_seconds', 'progress_events',
                   'attempt', 'max_attempts')
        if update.get('state') == 'started':
            if self.value.get('state') != 'retrying':
                self.value.update(attempt=1, max_attempts=3)
            for key in numeric:
                if key not in ('attempt', 'max_attempts'):
                    self.value.pop(key, None)
        for key in numeric:
            value = update.get(key)
            if type(value) in (int, float) and 0 <= value <= 10**12 and math.isfinite(value):
                self.value[key] = value
        if update.get('state') in ('preparing', 'started', 'running', 'retrying', 'idle_timeout',
                                    'completed', 'start_failed', 'cli_failed', 'invalid_json',
                                    'output_too_large', 'incomplete_response'):
            self.value['state'] = update['state']
        if update.get('transport') in ('responses_http', 'codex_cli'):
            self.value['transport'] = update['transport']
        self.value['progress_updated_at'] = time.time()
        query = 'UPDATE ' + self.table + " SET progress=? WHERE id=? AND status='running'"
        arguments = [json.dumps(self.value, ensure_ascii=False, allow_nan=False), self.identity]
        if self.revision is not None:
            query += ' AND revision=?'
            arguments.append(self.revision)
        with self.store.connection() as db:
            db.execute(query, arguments)
