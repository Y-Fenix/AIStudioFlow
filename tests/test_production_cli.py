import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


class ProductionCliTests(unittest.TestCase):
    def test_create_status_and_actions_do_not_dispatch_models(self):
        with tempfile.TemporaryDirectory() as folder:
            base=[sys.executable,str(ROOT/'tools/run_production.py'),'--database',str(Path(folder)/'db.sqlite')]
            def call(args):
                result=subprocess.run([*base,*args],cwd=ROOT,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)
            run=call(['create','--new-project','CLI fixture','--brief','memory match with six pairs','--name','CLI fixture'])
            self.assertEqual(run['status'],'queued')
            self.assertEqual(run['progress']['completed'],0)
            base.extend(['--studio',run['studio_id'],'--project',run['project_id']])
            detail=call(['status','--id',run['id'],'--full'])
            self.assertTrue(all(s['status']=='pending' for s in detail['steps']))
            self.assertEqual(detail['artifacts'],[])
            self.assertEqual(call(['pause','--id',run['id']])['status'],'paused')
            self.assertEqual(call(['resume','--id',run['id']])['status'],'queued')
            self.assertEqual(call(['cancel','--id',run['id']])['status'],'cancelled')
