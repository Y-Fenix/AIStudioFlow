import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import static_review as sr
from departments.testing.QA_review_checkpoints import QA_checkpoint_scope
from tests.test_static_review import CASE, SOURCE, assertion


class QA_NativeExecutionTests(unittest.TestCase):
    def test_failed_correction_preserves_valid_cases_and_retry_requests_only_missing_case(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Assets').mkdir();(root/'Assets/Reward.cs').write_text(SOURCE)
            binding=dict(repository=str(root),project_root=str(root),branch='test',commit='abc',code_fingerprint='same')
            cases=[copy.deepcopy(CASE),{**copy.deepcopy(CASE),'id':'C2'}]
            class Agent:
                calls=[]
                def request_json(self,prompt,root,schema,**options):
                    ids=schema['properties']['results']['items']['properties']['case_id']['enum'];self.calls.append(ids)
                    rows=[{'case_id':i,'assertions':[assertion(0),assertion(1)]} for i in ids]
                    if len(self.calls)==1:rows[-1]['assertions'][0]['call_chain'][0]['quote']='bad quote'
                    return {'shared_analysis':'shared','results':rows}
            agent=Agent()
            def bad_repair(*args,**kwargs):return {'results':[{'case_id':'C2','assertions':[]}]}
            with patch('server.gagasort.inspect_project',return_value=binding),QA_checkpoint_scope(root/'cache'):
                first=sr.execute_static(binding,cases,[],root/'evidence',native_client=agent,native_repair=bad_repair)
                self.assertEqual(first['results'][1]['status'], 'insufficient_evidence')
                self.assertTrue(all(a['status'] == 'insufficient_evidence' for a in first['results'][1]['assertions']))
                report=sr.execute_static(binding,cases,[],root/'evidence',native_client=agent)
            self.assertEqual(agent.calls,[['C1','C2'],['C2']])
            self.assertEqual(report['checkpoint_reused'],1)

    def test_one_bad_quote_repairs_only_that_case_without_repeating_project_investigation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Assets').mkdir();(root/'Assets/Reward.cs').write_text(SOURCE)
            binding=dict(repository=str(root),project_root=str(root),branch='test',commit='abc',code_fingerprint='same')
            cases=[copy.deepcopy(CASE),{**copy.deepcopy(CASE),'id':'C2'}]
            class Agent:
                calls=0
                def request_json(self,*args,**kwargs):
                    self.calls+=1
                    output={'shared_analysis':'shared','results':[{'case_id':c['id'],'assertions':[assertion(0),assertion(1)]} for c in cases]}
                    output['results'][1]['assertions'][0]['call_chain'][0]['quote']='invented()'
                    return output
            agent=Agent();repairs=[]
            def repair(prompt,**options):
                repairs.append(prompt)
                payload=json.loads(prompt.split('校正资料：\n',1)[1])
                self.assertEqual(payload['actual_source_windows'][0]['text'],SOURCE)
                self.assertIn('1: '+SOURCE.splitlines()[0],payload['actual_source_windows'][0]['numbered_text'])
                self.assertEqual(payload['case']['id'],'C2')
                return {'shared_analysis':'引用格式校正','results':[{'case_id':'C2','assertions':[assertion(0),assertion(1)]}]}
            with patch('server.gagasort.inspect_project',return_value=binding):
                report=sr.execute_static(binding,cases,[],root/'evidence',native_client=agent,native_repair=repair)
            self.assertEqual(agent.calls,1);self.assertEqual(len(repairs),1)
            self.assertEqual(len(report['results']),2)

    def test_real_batch_boundary_preserves_order_checkpoints_and_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            (root / 'Assets/Reward.cs').write_text(SOURCE)
            binding = dict(repository=str(root), project_root=str(root), branch='test', commit='abc', code_fingerprint='same')
            cases = [{**copy.deepcopy(CASE), 'id': f'C{i}'} for i in range(23)]
            class Agent:
                calls = []
                def request_json(self, prompt, root, schema, **options):
                    ids = schema['properties']['results']['items']['properties']['case_id']['enum']
                    self.calls.append(ids)
                    return {'shared_analysis': '共享入口调查', 'results': [
                        {'case_id': i, 'assertions': [assertion(0), assertion(1)]} for i in reversed(ids)]}
            agent = Agent()
            with patch('server.gagasort.inspect_project', return_value=binding), \
                 QA_checkpoint_scope(root / 'checkpoints'):
                report = sr.execute_static(binding, cases, [], root / 'evidence', native_client=agent)
                self.assertEqual(len(agent.calls), 2)
                self.assertEqual([r['case_id'] for r in report['results']], [c['id'] for c in cases])
                sr.validate_coverage(report, cases)
                again = sr.execute_static(binding, cases, [], root / 'evidence', native_client=agent)
                self.assertEqual(again['checkpoint_reused'], 23)
                self.assertEqual(len(agent.calls), 2)
                self.assertEqual(again['execution_engine'], 'project_agent')
                # Serialized level bytes are used by native source tools. A
                # binary change must invalidate cache even if text baseline is unchanged.
                (root / 'Assets/level.bytes').write_bytes(b'changed level')
                changed=sr.execute_static(binding,cases,[],root/'evidence',native_client=agent)
                self.assertEqual(changed['checkpoint_reused'],0)
                self.assertEqual(len(agent.calls),4)

    def test_generated_java_review_uses_real_source_without_git_or_unity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            name = 'app/src/main/java/game/Main.java'
            (root / name).parent.mkdir(parents=True)
            (root / name).write_text(SOURCE)
            (root / 'assets').mkdir()
            (root / 'assets/game-spec.json').write_text('{"time_limit":60}')
            (root / 'AndroidManifest.xml').write_text('<manifest/>')
            (root / 'README.md').write_text('Rebuild with the documented SDK tools.')
            (root / 'build.log').write_text('APK signature verified.')
            case = {**copy.deepcopy(CASE), 'id': 'J1'}
            class Agent:
                def request_json(self, *_args, **_kwargs):
                    rows = [assertion(0), assertion(1)]
                    for row in rows:
                        row['call_chain'][0]['file'] = name
                    rows[0]['call_chain'].append({'file':'assets/game-spec.json','line':1,'quote':'{"time_limit":60}'})
                    rows[0]['call_chain'].append({'file':'AndroidManifest.xml','line':1,'quote':'<manifest/>'})
                    rows[0]['call_chain'].append({'file':'README.md','line':1,'quote':'Rebuild with the documented SDK tools.'})
                    rows[0]['call_chain'].append({'file':'build.log','line':1,'quote':'APK signature verified.'})
                    return {'shared_analysis': '真实Java源码', 'results': [{'case_id': 'J1', 'assertions': rows}]}
            with patch('server.core.codex_agent.CodexAgent', return_value=Agent()), \
                 patch('server.gagasort.inspect_project', side_effect=AssertionError('No fake Unity binding')):
                result = sr.QA_review_generated_workspace(root, [case])
            self.assertEqual(result['results'][0]['status'], 'passed')
            self.assertEqual(result['findings'], [])
            self.assertEqual(result['runtime_status'], 'not_run')

    def test_compacted_searches_do_not_repeat_unread_lists_or_mutate_trace(self):
        requests = [{'search': [{'term': str(i), 'hits': [], 'unread_files': ['Assets/bad.cs']} for i in range(8)]}]
        original = copy.deepcopy(requests)
        view = sr.QA_compact_search_history(requests)
        self.assertEqual(requests, original)
        self.assertEqual(json.dumps(view).count('Assets/bad.cs'), 1)
        self.assertIn('unread', json.dumps(view))

    def test_project_prompt_uses_summary_for_large_generated_evidence(self):
        from departments.testing.QA_native_review import QA_agent_prompt
        prompt=QA_agent_prompt([CASE],[])
        self.assertIn('level-validation.json',prompt)
        self.assertIn('20000',prompt)
        self.assertIn('汇总',prompt)
