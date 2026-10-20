import tempfile,time,json,hashlib
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from server.editor_bridge import preflight,submit

class EditorBridgeTests(unittest.TestCase):
    def test_stale_heartbeat_cannot_submit_and_parallel_requests_are_serialized(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);mailbox=root/'mailbox';mailbox.mkdir()
            source=root/'Assets/Editor/Tools/TEST/TEST_RealGameUiSmokeWindow.cs';source.parent.mkdir(parents=True);source.write_text('// fixture')
            binding={'repository':folder,'project_root':folder,'branch':'master','commit':'sha','code_fingerprint':'hash'}
            heartbeat={'projectRoot':folder,'runnerSha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                       'unix':int(time.time())-30,'playing':True,'paused':False,'compiling':False}
            path=mailbox/'heartbeat.json';path.write_text(json.dumps(heartbeat))
            with patch('server.gagasort.inspect_project',return_value=binding):
                self.assertFalse(preflight(binding,mailbox)['ready'])
                with self.assertRaises(ValueError):submit(binding,mailbox)
                path.write_text(json.dumps({**heartbeat,'unix':int(time.time())}))
                def dispatch():
                    try:return submit(binding,mailbox)
                    except ValueError:return None
                with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:dispatch(),range(2)))
                self.assertEqual(sum(bool(r) for r in results),1)
                request=json.loads(next(mailbox.glob('*.request.json')).read_text())
                self.assertEqual(request['mode'],'settings_smoke')
                self.assertNotIn('allowAccountChanges',request)
                self.assertEqual(request['projectRoot'],folder)
