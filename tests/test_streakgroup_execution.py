import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess
from server.streakgroup_execution import execute_streakgroup, classify_result, SUITES


class StreakgroupExecutionTests(unittest.TestCase):
    def test_assertion_stack_is_required_to_classify_failure(self):
        summary = SUITES[0][3]
        log = ('Unhandled exception. System.Exception: expected reward\n'
               '   at Program.Check(Boolean b, String message) in /tmp/Program.cs:line 2\n')
        self.assertEqual(classify_result(134, log, summary)[0], 'failed')
        self.assertEqual(classify_result(0, log, summary)[0], 'runner_error')
        self.assertEqual(classify_result(1, 'error CS1001: syntax error', summary)[0], 'runner_error')
        self.assertEqual(classify_result(134, 'Unhandled exception. System.Exception: resource error\n'
                          '   at ResourceLoader.Load()', summary)[0], 'runner_error')

    def test_only_exit_zero_and_actual_summary_can_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'tools').mkdir()
            for name in ('test-streakgroup-event.py','test-streakgroup-rank-animation.py'):
                (root/'tools'/name).touch()
            sdk=root/'sdk';sdk.mkdir();(sdk/'dotnet').touch()
            binding={'repository':directory,'branch':'master','commit':'sha','code_fingerprint':'hash'}
            with patch('server.streakgroup_execution.SDK',sdk), patch('server.gagasort.inspect_project',return_value=binding), patch('server.streakgroup_execution.run',side_effect=[
                CompletedProcess([],0,'通过：StreakGroupEvent 配置，共 12 项断言。',''),
                CompletedProcess([],0,'没有通过摘要','')]):
                report=execute_streakgroup(binding,root/'evidence')
            self.assertEqual(report['counts'],{'passed':1,'failed':0,'runner_error':1})
            self.assertEqual(report['results'][0]['assertion_count'],12)
            self.assertIsNone(report['build'])
            self.assertTrue(Path(report['evidence']).is_file())
            self.assertIn('套件',report['scope'])
