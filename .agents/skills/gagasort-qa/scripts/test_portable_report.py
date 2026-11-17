#!/usr/bin/env python3
"""Portable format regression tests. Fixtures are synthetic, not audit findings."""
import base64
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from export_portable_report import build_viewer, csv_rows, digest, export_bundle, load_run, safe_path
from bug_register import register_csv


class PortableReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'new-batch'
        self.headers = ['缺陷描述', '测试步骤', '空列']
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(self.headers)
        writer.writerow(['TEST-001 合成测试数据', '第一步\n第二步,"引号"', ''])
        self.csv = stream.getvalue().encode('utf-8-sig')
        self.picture = b'fixture-image-bytes'
        self.source = '\n'.join('source line ' + str(i) for i in range(1, 501))
        self.assets = {
            'old.png': {'base64': base64.b64encode(self.picture).decode(), 'mime': 'image/png'},
            'sources/A.cs.txt': {'text': self.source, 'sha256': digest(self.source.encode())},
        }
        self.view = {
            'baseline': {'run_id': 'fixture-only', 'head': 'test'},
            'presentation': {'conclusion': '合成测试，不是审计结果'},
            'features': [{'category_plain': '系统', 'name_plain': 'fixture',
                          'check_plain': '合成输入', 'outcome': 'test', 'trace': [{'path': 'A.cs', 'line': 100}]}],
            'issues': [{'id': 'TEST-001', 'confirmed': True}],
            'bug_register': {'headers': self.headers, 'csv': 'not-to-embed', 'rows': [
                {'id': 'TEST-001', 'fields': {'空列': ''}, 'detail': {'steps': ['fixture']}}]},
            'runs': {}, 'level_audit': {'risks': [{'level_id': '1', 'caption': 'fixture', 'image': 'old.png', 'steps': []}],
                                       'samples': [{'level_id': '2', 'caption': 'duplicate', 'image': 'old.png', 'steps': []}]},
            'assets': {'large-log': 'must-not-copy'}, 'feishu_authorized': True,
        }

    def export(self):
        return export_bundle(self.view, self.csv, self.assets.get, self.output, 'fixture only')

    def test_preserves_csv_and_only_three_entries(self):
        result = self.export()
        self.assertEqual(set(p.name for p in self.output.iterdir()), {'report.md', 'bugs.csv', 'images'})
        self.assertEqual((self.output / 'bugs.csv').read_bytes(), self.csv)
        parsed = csv_rows(self.csv, self.headers, ['TEST-001'])
        self.assertEqual(parsed[0][1], '第一步\n第二步,"引号"')
        self.assertEqual(parsed[0][-1], '')
        md = (self.output / 'report.md').read_text()
        package = json.loads(md.split('```gagasort-report-v1\n')[1].split('\n```')[0])
        self.assertFalse(package['view']['feishu_authorized'])
        self.assertNotIn('assets', package['view'])
        self.assertNotIn('fields', package['view']['bug_register']['rows'][0])
        self.assertNotIn('csv', package['view']['bug_register'])
        self.assertEqual(result['images'], 1)
        self.assertEqual((self.output / package['images'][0]['path']).read_bytes(), self.picture)
        note = package['evidence_notes']['sources/A.cs.txt']
        self.assertIn('100 | source line 100', note['text'])
        self.assertNotIn('source line 500', note['text'])
        self.assertEqual(note['sha256'], digest(note['text'].encode()))
        self.assertEqual(self.view['feishu_authorized'], True)
        self.assertIn('fields', self.view['bug_register']['rows'][0])

    def test_never_overwrites_existing_batch(self):
        self.export()
        before = (self.output / 'report.md').read_bytes()
        with self.assertRaisesRegex(ValueError, '已存在'):
            self.export()
        self.assertEqual(before, (self.output / 'report.md').read_bytes())

    def test_live_register_csv_roundtrips_without_duplicate_bom(self):
        fields = dict(zip(self.headers, ['TEST-001 合成测试数据', '第一步\n第二步,"引号"', '']))
        self.view['bug_register']['rows'][0]['fields'] = fields
        self.view['bug_register']['csv'] = register_csv(self.view['bug_register'])
        with patch('render_report.validate'), patch('render_report.prepare_view', return_value=self.view):
            view, raw, _ = load_run(Path(self.temp.name), {})
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        self.assertFalse(raw.startswith(b'\xef\xbb\xbf\xef\xbb\xbf'))
        rows = csv_rows(raw, view['bug_register']['headers'], ['TEST-001'])
        self.assertEqual(rows[0][1], '第一步\r\n第二步,"引号"')
        export_bundle(view, raw, self.assets.get, self.output, 'fixture only')

    def test_missing_or_invalid_picture_stops_without_partial_batch(self):
        self.assets.pop('old.png')
        with self.assertRaisesRegex(ValueError, '图片'):
            self.export()
        self.assertFalse(self.output.exists())

    def test_csv_id_columns_and_confirmed_set_must_match(self):
        for raw in (self.csv.replace(b'TEST-001', b'TEST-002'), self.csv.replace('空列'.encode(), b'changed')):
            with self.assertRaises(ValueError):
                export_bundle(self.view, raw, self.assets.get, self.output, 'fixture')
        self.view['issues'][0]['confirmed'] = False
        with self.assertRaisesRegex(ValueError, '已确认'):
            self.export()

    def test_path_escape_rejected(self):
        for path in ('../image.png', '/tmp/image.png', 'C:/tmp/a', 'a\\b'):
            with self.assertRaises(ValueError):
                safe_path(path)

    def test_viewer_is_generic_and_uses_pinned_template(self):
        viewer = build_viewer()
        self.assertNotIn('__REPORT_TEMPLATE__', viewer)
        self.assertIn('webkitdirectory', viewer)
        self.assertIn('connect-src', viewer)
        self.assertIn('portableHash', viewer)
        self.assertNotIn('TEST-001 合成测试数据', viewer)


if __name__ == '__main__':
    unittest.main()
