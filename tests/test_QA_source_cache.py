import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server.static_review import SourceCatalog


class QA_SourceCacheTests(unittest.TestCase):
    def test_search_does_not_check_database_for_every_file(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder) / 'Assets'
            assets.mkdir()
            for index in range(100):
                (assets / f'{index}.cs').write_text('Grant();\n')
            catalog = SourceCatalog(folder)
            with patch('server.static_review.check_cancelled') as cancelled:
                catalog.QA_search_many(['Grant'])
                self.assertLessEqual(cancelled.call_count, 5)
                self.assertGreaterEqual(cancelled.call_count, 2)

    def test_search_checks_cancellation_before_and_after_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = SourceCatalog(folder)
            with patch('server.static_review.check_cancelled', side_effect=[None, ValueError('cancelled')]):
                with self.assertRaisesRegex(ValueError, 'cancelled'):
                    catalog.QA_search_many(['Grant'])

    def test_search_checks_cancellation_during_long_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder) / 'Assets'
            assets.mkdir()
            for index in range(4):
                (assets / f'{index}.cs').write_text('Grant();\n')
            catalog = SourceCatalog(folder)
            with patch('server.static_review.time.monotonic', side_effect=[0, .1, .3]), \
                 patch('server.static_review.check_cancelled', side_effect=[None, ValueError('cancelled')]):
                with self.assertRaisesRegex(ValueError, 'cancelled'):
                    catalog.QA_search_many(['Grant'])

    def test_batch_search_scans_each_file_once_and_matches_individual_searches(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'Assets/Reward.cs'
            source.parent.mkdir()
            source.write_text('Grant();\nReward();\n')
            catalog = SourceCatalog(folder)
            expected = [catalog.search(term) for term in ('Grant', 'Reward')]
            with patch.object(catalog, 'read', wraps=catalog.read) as read:
                self.assertEqual(catalog.QA_search_many(['Grant', 'Reward']), expected)
                self.assertEqual(read.call_count, 1)

    def test_removed_source_is_a_reportable_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'Assets/Reward.cs'
            source.parent.mkdir()
            source.write_text('Grant();\n')
            catalog = SourceCatalog(folder)
            source.unlink()
            with self.assertRaises(ValueError):
                catalog.read('Assets/Reward.cs')
            self.assertEqual(catalog.search('Grant')['unread_files'], ['Assets/Reward.cs'])

    def test_repeated_search_reuses_source_but_detects_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'Assets/Reward.cs'
            source.parent.mkdir()
            source.write_text('Grant();\n')
            catalog = SourceCatalog(folder)
            original = Path.read_text
            reads = []
            def observed(path, *args, **kwargs):
                reads.append(path)
                return original(path, *args, **kwargs)
            with patch.object(Path, 'read_text', observed):
                self.assertEqual(len(catalog.search('Grant')['hits']), 1)
                self.assertEqual(len(catalog.search('Reward')['hits']), 0)
                self.assertEqual(len(reads), 1)
                source.write_text('RewardChanged();\n')
                self.assertEqual(len(catalog.search('RewardChanged')['hits']), 1)
                self.assertEqual(len(catalog.search('Grant')['hits']), 0)
                self.assertEqual(len(reads), 2)

    def test_cached_file_cannot_be_replaced_by_symlink_parent(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root = Path(folder)
            assets = root / 'Assets'
            assets.mkdir()
            (assets / 'Reward.cs').write_text('Safe();\n')
            catalog = SourceCatalog(root)
            catalog.read('Assets/Reward.cs')
            (assets / 'Reward.cs').unlink()
            assets.rmdir()
            (Path(outside) / 'Reward.cs').write_text('Secret();\n')
            assets.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                catalog.read('Assets/Reward.cs')
