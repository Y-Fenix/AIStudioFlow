import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from server.processes import cancellation_scope, run


class ProcessTests(unittest.TestCase):
    def test_cancel_stops_parent_and_child_before_child_can_write(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory)/'ready'
            escaped = Path(directory)/'escaped'
            child = 'import time; from pathlib import Path; time.sleep(1.5); Path('+repr(str(escaped))+').write_text("leaked")'
            parent = 'import subprocess,sys,time; from pathlib import Path; subprocess.Popen([sys.executable,"-c",'+repr(child)+']); Path('+repr(str(ready))+').touch(); time.sleep(30)'
            with cancellation_scope(lambda: ready.exists()):
                with self.assertRaisesRegex(ValueError, '取消'):
                    run([sys.executable,'-c',parent], capture_output=True, text=True, timeout=10)
            threading.Event().wait(1.7)
            self.assertFalse(escaped.exists())

    def test_timeout_also_stops_child_and_normal_output_survives(self):
        with cancellation_scope(lambda: False):
            with self.assertRaises(__import__('subprocess').TimeoutExpired):
                run([sys.executable,'-c','import time; time.sleep(30)'], timeout=.1)
            result = run([sys.executable,'-c','print(input())'], input='hello', capture_output=True,text=True,timeout=3)
        self.assertEqual(result.stdout,'hello\n')

    def test_tick_observes_running_process_before_completion(self):
        ticks=[]
        result=run([sys.executable,'-c','import time;print("ready",flush=True);time.sleep(.3)'],
                   capture_output=True,text=True,timeout=3,on_tick=lambda:ticks.append(True))
        self.assertTrue(ticks)
        self.assertEqual(result.stdout,'ready\n')

    def test_responsive_process_can_run_longer_than_idle_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            progress = Path(directory)/'progress'
            progress.touch()
            observed = [0]
            def probe():
                size = progress.stat().st_size
                changed = size != observed[0]
                observed[0] = size
                return changed
            script = 'import time; from pathlib import Path; p=Path('+repr(str(progress))+'); '+"\nfor i in range(8):\n p.write_text('x'*(i+1)); time.sleep(.1)"
            result = run([sys.executable,'-c',script], capture_output=True,
                         idle_timeout=.4, activity_probe=probe)
            self.assertEqual(result.returncode,0)
            self.assertEqual(progress.read_text(),'xxxxxxxx')

    def test_heartbeat_and_process_liveness_do_not_renew_idle_deadline(self):
        ticks=[]
        started=time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            run([sys.executable,'-c','import time; time.sleep(30)'],
                idle_timeout=.3,activity_probe=lambda:False,on_tick=lambda:ticks.append(True))
        self.assertTrue(ticks)
        self.assertLess(time.monotonic()-started,2)

    def test_idle_after_progress_stops_entire_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            ready=Path(directory)/'ready';escaped=Path(directory)/'escaped'
            child='import time; from pathlib import Path; time.sleep(1); Path('+repr(str(escaped))+').touch()'
            script='import subprocess,sys,time; from pathlib import Path; subprocess.Popen([sys.executable,"-c",'+repr(child)+']); Path('+repr(str(ready))+').touch(); time.sleep(30)'
            observed=[False]
            def probe():
                activity=ready.exists() and not observed[0]
                observed[0]=ready.exists()
                return activity
            with self.assertRaises(subprocess.TimeoutExpired):
                run([sys.executable,'-c',script],idle_timeout=.3,activity_probe=probe)
            threading.Event().wait(1.1)
            self.assertFalse(escaped.exists())

    def test_cancel_still_interrupts_idle_wait(self):
        calls=[]
        def cancelled():
            calls.append(True)
            return len(calls)>2
        with cancellation_scope(cancelled):
            with self.assertRaisesRegex(ValueError,'取消'):
                run([sys.executable,'-c','import time; time.sleep(30)'],
                    idle_timeout=5,activity_probe=lambda:False)
