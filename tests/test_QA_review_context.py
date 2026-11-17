import unittest
from departments.testing.QA_review_context import QA_evidence_keys, QA_primary_affinity, QA_compact_source_search


class QA_ReviewContextTests(unittest.TestCase):
    def test_keys_use_exact_metadata_without_guessing_from_title(self):
        self.assertEqual(QA_evidence_keys({'title': 'Reward reward'}), [])
        self.assertEqual(QA_evidence_keys({'point_ids': 'P1'}), [])
        self.assertEqual(QA_evidence_keys({'point_ids': ['P1', 'P1', None]}), [('point', 'P1')])
        self.assertEqual(QA_primary_affinity({'module': 'reward', 'point_ids': ['P1']}), ('module', 'reward'))

    def test_search_text_is_removed_only_when_exact_original_line_is_available(self):
        original = [{'search': [{'term': 'Grant', 'hits': [
            {'file': 'A.cs', 'line': 1, 'text': 'Grant();'},
            {'file': 'A.cs', 'line': 2, 'text': 'not read'},
            {'file': 'A.cs', 'line': 3, 'text': 'different'},
        ], 'truncated': True, 'unread_files': ['B.cs']}]}]
        compact = QA_compact_source_search(original, {'A.cs': 'Grant();\n\nActual();\n'})
        hits = compact[0]['search'][0]['hits']
        self.assertNotIn('text', hits[0])
        self.assertTrue(hits[0]['text_in_sources'])
        self.assertEqual(hits[1]['text'], 'not read')
        self.assertEqual(hits[2]['text'], 'different')
        self.assertTrue(compact[0]['search'][0]['truncated'])
        self.assertEqual(original[0]['search'][0]['hits'][0]['text'], 'Grant();')
