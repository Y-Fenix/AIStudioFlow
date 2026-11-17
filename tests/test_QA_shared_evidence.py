import json
import tempfile
import unittest
from pathlib import Path
from server import static_review as sr
from tests.test_static_review import CASE, SOURCE, assertion


class QA_SharedEvidenceTests(unittest.TestCase):
    def test_raw_evidence_pool_rejects_fabricated_text_and_does_not_cross_catalogs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            (root / 'Assets/A.cs').write_text('Known();\nNotRead();\n')
            catalog = sr.SourceCatalog(root)
            catalog.QA_publish_evidence(CASE, {'Assets/A.cs': 'Fabricated();\n'})
            search = [{'hits': [{'file': 'Assets/A.cs', 'line': 1}]}]
            self.assertEqual(catalog.QA_search_evidence(search), {})
            catalog.QA_publish_evidence(CASE, {'Assets/A.cs': 'Known();\n\n'})
            self.assertEqual(catalog.QA_search_evidence([{'hits': [{'file': 'Assets/A.cs', 'line': 2}]}]), {})
            self.assertTrue(catalog.QA_search_evidence(search))
            self.assertEqual(sr.SourceCatalog(root).QA_search_evidence(search), {})

    def test_multi_point_seed_respects_combined_byte_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            catalog = None
            for name in ('A', 'B'):
                (root / f'Assets/{name}.cs').write_text('x' * 80000)
            catalog = sr.SourceCatalog(root)
            catalog.QA_publish_evidence({'point_ids': ['P1']}, {'Assets/A.cs': 'x' * 80000})
            catalog.QA_publish_evidence({'point_ids': ['P2']}, {'Assets/B.cs': 'x' * 80000})
            seed = catalog.QA_seed_evidence({'point_ids': ['P1', 'P2']})
            self.assertLessEqual(sum(len(s.encode()) for s in seed.values()), 120000)
            self.assertEqual(len(seed), 1)

    def test_unrelated_case_can_retrieve_shared_source_only_after_its_own_matching_search(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            path = root / 'Assets/Reward.cs'
            path.write_text(SOURCE)
            catalog, payloads = sr.SourceCatalog(root), []
            catalog.QA_publish_evidence(CASE, {'Assets/Reward.cs': SOURCE})
            self.assertEqual(catalog.QA_seed_evidence(CASE), {})
            class Client:
                def request_json(self, prompt):
                    p = json.loads(prompt.split('审查数据：\n', 1)[1])
                    payloads.append(p)
                    if len(payloads) == 1:
                        return {'search': ['Grant']}
                    return {'assertions': [assertion(0), assertion(1)]}
            result, trace = sr.review_case(CASE, [], catalog, Client())
            self.assertEqual(len(payloads), 2)
            self.assertEqual(payloads[-1]['sources']['Assets/Reward.cs'], SOURCE)
            self.assertEqual(result['case_id'], CASE['id'])
            self.assertEqual(trace['retrieved_source_files'], ['Assets/Reward.cs'])
            path.write_text('Changed();\n')
            self.assertEqual(catalog.QA_search_evidence([{'hits': [{'file': 'Assets/Reward.cs', 'line': 1}]}]), {})

    def test_exact_test_point_reuses_sources_without_module_and_checks_each_case(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            (root / 'Assets/Reward.cs').write_text(SOURCE)
            catalog, payloads = sr.SourceCatalog(root), []
            class Client:
                def request_json(self, prompt):
                    p = json.loads(prompt.split('审查数据：\n', 1)[1])
                    payloads.append(p)
                    return {'assertions': [assertion(0), assertion(1)]} if p['sources'] else {'read': ['Assets/Reward.cs']}
            first = {**CASE, 'point_ids': ['P1']}
            second = {**CASE, 'id': 'C2', 'point_ids': ['P1', 'P2']}
            sr.review_case(first, [], catalog, Client())
            result, trace = sr.review_case(second, [], catalog, Client())
            self.assertEqual(len(payloads), 3)
            self.assertEqual(result['case_id'], 'C2')
            self.assertEqual(trace['shared_source_files'], ['Assets/Reward.cs'])
            self.assertEqual(catalog.QA_seed_evidence({**CASE, 'point_ids': ['P3']}), {})
            (root / 'Assets/Reward.cs').write_text('Changed();\n')
            self.assertEqual(catalog.QA_seed_evidence(second), {})

    def test_shared_windows_merge_instead_of_forgetting_previous_source_ranges(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            (root / 'Assets/A.cs').write_text('First();\nMiddle();\nLast();\n')
            catalog, case = sr.SourceCatalog(root), {**CASE, 'point_ids': ['P1']}
            catalog.QA_publish_evidence(case, {'Assets/A.cs': 'First();\n\n\n'})
            catalog.QA_publish_evidence(case, {'Assets/A.cs': '\n\nLast();\n'})
            self.assertEqual(catalog.QA_seed_evidence(case)['Assets/A.cs'], 'First();\n\nLast();\n')

    def test_catalog_is_discovered_on_demand_without_losing_access_to_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            for i in range(205):
                (root / f'Assets/Reward{i:03}.cs').write_text(SOURCE)
            payloads = []
            class Client:
                def request_json(self, prompt):
                    payloads.append(json.loads(prompt.split('审查数据：\n', 1)[1]))
                    return {'find_files': [{'query': 'reward', 'offset': 200}]}
            _, trace = sr.review_case(CASE, [], sr.SourceCatalog(root), Client(), max_rounds=2)
            self.assertNotIn('file_catalog_by_directory', payloads[0])
            self.assertEqual(payloads[0]['file_catalog_summary']['total_files'], 205)
            found = trace['requests'][0]['find_files'][0]
            self.assertEqual(found['total'], 205)
            self.assertEqual(len(found['files']), 5)
            self.assertFalse(found['has_more'])
            self.assertIn('Assets/Reward204.cs', found['files'])
            first = sr.SourceCatalog(root).QA_find_files({'query': '', 'offset': 0})
            self.assertEqual(len(first['files']), 200)
            self.assertEqual(first['next_offset'], 200)
            self.assertTrue(first['has_more'])
            self.assertIn('error', sr.SourceCatalog(root).QA_find_files({'query': '', 'offset': -1}))
            self.assertIn('error', sr.SourceCatalog(root).QA_find_files('invalid'))

    def test_changed_search_result_is_not_discarded(self):
        first = {'term': 'Grant', 'hits': [{'file': 'Assets/A.cs', 'line': 1, 'text': 'Grant'}], 'truncated': False, 'unread_files': []}
        changed = {**first, 'hits': []}
        requests = [{'search': [first]}, {'search': [first]}, {'search': [changed]}]
        compact = sr.QA_compact_search_history(requests)
        self.assertEqual([s for item in compact for s in item.get('search', [])], [first, changed])

    def test_repeated_search_results_are_not_resent_but_trace_is_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            (root / 'Assets/Reward.cs').write_text(SOURCE)
            payloads = []
            class Client:
                def request_json(self, prompt):
                    payloads.append(json.loads(prompt.split('审查数据：\n', 1)[1]))
                    return {'search': ['Grant']}
            _, trace = sr.review_case(CASE, [], sr.SourceCatalog(root), Client(), max_rounds=3)
            self.assertEqual(len(trace['requests']), 3)
            searches = [s for r in payloads[-1]['requests'] for s in r.get('search', [])]
            self.assertEqual(len(searches), 1)
            self.assertEqual(searches[0]['hits'][0]['file'], 'Assets/Reward.cs')

    def test_module_reuses_sources_but_still_requests_independent_assertions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            (root / 'Assets/Reward.cs').write_text(SOURCE)
            catalog = sr.SourceCatalog(root)
            payloads = []
            class Client:
                def request_json(self, prompt):
                    payload = json.loads(prompt.split('审查数据：\n', 1)[1])
                    payloads.append(payload)
                    if not payload['sources']:
                        return {'read': ['Assets/Reward.cs']}
                    return {'assertions': [assertion(0), assertion(1)]}
            first = {**CASE, 'module': 'reward'}
            second = {**CASE, 'id': 'C2', 'module': 'reward'}
            sr.review_case(first, [], catalog, Client())
            result, _ = sr.review_case(second, [], catalog, Client())
            self.assertEqual(len(payloads), 3)
            self.assertEqual(payloads[-1]['case']['id'], 'C2')
            self.assertEqual(result['case_id'], 'C2')
            self.assertEqual(payloads[-1]['sources']['Assets/Reward.cs'], SOURCE)

    def test_changed_source_and_unrelated_modules_cannot_inherit_old_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            path = root / 'Assets/Reward.cs'
            path.write_text(SOURCE)
            catalog = sr.SourceCatalog(root)
            catalog.QA_publish_evidence({'module': 'reward'}, {'Assets/Reward.cs': SOURCE})
            self.assertEqual(catalog.QA_seed_evidence({'module': 'ads'}), {})
            path.write_text('Changed();\n')
            self.assertEqual(catalog.QA_seed_evidence({'module': 'reward'}), {})

    def test_no_explicit_module_does_not_guess_shared_business_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = sr.SourceCatalog(folder)
            catalog.QA_publish_evidence(CASE, {'Assets/Reward.cs': SOURCE})
            self.assertEqual(catalog.QA_seed_evidence(CASE), {})
