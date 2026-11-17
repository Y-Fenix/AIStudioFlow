"""Synthetic workflow fixtures; no product audit or browser success is inferred."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import finalize_report
import publish_report
from export_portable_report import build_viewer
from portable_delivery import FORMAT, sha256, snapshot
import test_portable_report as fixtures
from export_portable_report import export_bundle


class PublishReportTest(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.PortableReportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for key in ("temp", "headers", "csv", "picture", "source", "assets", "view"):
            setattr(self, key, getattr(fixture, key))
        self.run = Path(self.temp.name) / 'full-audit-20261030-160000'
        self.run.mkdir()
        self.stage = self.run / 'portable-delivery-fixture'
        self.stage.mkdir()
        self.viewer = self.stage / '查看报告.html'
        self.viewer.write_text(build_viewer(), encoding='utf-8')
        self.output = self.stage / 'batch'
        self.export()
        self.target = Path(self.temp.name) / 'quality' / '20261030-160000'
        (self.run / 'report-data.json').write_text('{"fixture": true}')
        self.seal()

    def export(self):
        return export_bundle(self.view, self.csv, self.assets.get, self.output, "fixture only")

    def save(self, name, data):
        (self.run / name).write_text(json.dumps(data, ensure_ascii=False))

    def seal(self):
        profile = json.loads((publish_report.SKILL / 'assets/delivery-profile.json').read_text())
        files = snapshot(self.viewer, self.output)
        self.save('portable-manifest.json', dict(directory=self.stage.name, files=files,
                  workflow_version=profile['workflow_version'], report_data_sha256=sha256(self.run / 'report-data.json')))
        self.save('portable-interaction-check.json', dict(status='passed', format=FORMAT,
                  files=files, checks=['synthetic fixture receipt, not real browser execution']))
        self.save('delivery-check.json', dict(report_ready=True, format=FORMAT, audit_complete=False,
                  portable_manifest_sha256=sha256(self.run / 'portable-manifest.json'),
                  interaction_receipt_sha256=sha256(self.run / 'portable-interaction-check.json')))

    def test_publishes_viewer_and_only_three_batch_entries(self):
        result = publish_report.publish(self.run, self.target)
        self.assertEqual(result['format'], FORMAT)
        self.assertEqual({p.name for p in self.target.iterdir()}, {'report.md', 'bugs.csv', 'images'})
        self.assertEqual(snapshot(self.target.parent / '查看报告.html', self.target), snapshot(self.viewer, self.output))
        with self.assertRaisesRegex(ValueError, '已存在'):
            publish_report.publish(self.run, self.target)

    def test_missing_or_unready_receipt_cannot_publish(self):
        self.save('delivery-check.json', dict(report_ready=False, format=FORMAT))
        with self.assertRaisesRegex(ValueError, '尚未通过'):
            publish_report.publish(self.run, self.target)
        self.assertFalse(self.target.exists())

    def test_mutated_csv_md_image_data_or_receipt_cannot_publish(self):
        for p in [self.output / 'bugs.csv', self.output / 'report.md', next((self.output / 'images').iterdir()),
                  self.run / 'report-data.json', self.run / 'portable-interaction-check.json']:
            original = p.read_bytes()
            p.write_bytes(original + b' changed')
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                publish_report.publish(self.run, self.target)
            self.assertFalse(self.target.exists())
            p.write_bytes(original)

    def test_existing_different_viewer_and_stale_workflow_rejected(self):
        self.target.parent.mkdir()
        viewer = self.target.parent / '查看报告.html'
        viewer.write_text('old viewer must stay')
        with self.assertRaisesRegex(ValueError, '版本不同'):
            publish_report.publish(self.run, self.target)
        self.assertEqual(viewer.read_text(), 'old viewer must stay')
        manifest = json.loads((self.run / 'portable-manifest.json').read_text())
        manifest['workflow_version'] = 'stale'
        self.save('portable-manifest.json', manifest)
        delivery = json.loads((self.run / 'delivery-check.json').read_text())
        delivery['portable_manifest_sha256'] = sha256(self.run / 'portable-manifest.json')
        self.save('delivery-check.json', delivery)
        with self.assertRaisesRegex(ValueError, '工作流版本'):
            publish_report.publish(self.run, self.target)

    def test_default_finalizer_does_not_render_legacy_html(self):
        # Mock only business evidence/runner. Real exporter + receipt verifier + publisher run.
        root = Path(self.temp.name)
        out = root / 'QA/results/full-audit-20261030-170000'
        out.mkdir(parents=True)
        (out / 'report-data.json').write_text('{"presentation":{"overall":"执行不完整"}}')
        version = json.loads((publish_report.SKILL / 'assets/delivery-profile.json').read_text())['workflow_version']
        def browser(command, **kwargs):
            self.assertIn('check_portable_report.cjs', command[1])
            files = snapshot(Path(command[2]), Path(command[3]))
            Path(command[5]).write_text(json.dumps(dict(status='passed', format=FORMAT,
                                       files=files, checks=['mock browser fixture'])))
            return type('Result', (), {'returncode': 0})()
        argv = ['finalize_report.py', '--root', str(root), '--evidence-dir', str(out), '--node', '/fixture/node']
        with patch('sys.argv', argv), redirect_stdout(io.StringIO()), \
             patch.object(finalize_report, 'verify_evidence', return_value={'workflow_version': version}), \
             patch.object(finalize_report, 'verify_execution_receipts'), \
             patch.object(finalize_report, 'completion', return_value=dict(ready_for_final=False, tasks=['fixture pending'], summary={})), \
             patch.object(finalize_report, 'build_quality_gate', return_value={}), \
             patch.object(finalize_report, 'export_results'), \
             patch.object(finalize_report, 'load_run', return_value=(self.view, self.csv, self.assets.get)), \
             patch.object(finalize_report, 'render', side_effect=AssertionError('legacy render invoked')), \
             patch.object(finalize_report.subprocess, 'run', side_effect=browser):
            self.assertEqual(finalize_report.main(), 2)
        delivery = json.loads((out / 'delivery-check.json').read_text())
        self.assertTrue(delivery['report_ready'])
        self.assertFalse(delivery['audit_complete'])
        self.assertEqual(delivery['format'], FORMAT)
        self.assertFalse((out / 'report.html').exists())
        result = publish_report.publish(out, root / 'new-quality/20261030-170000')
        self.assertEqual(result['format'], FORMAT)


if __name__ == '__main__':
    unittest.main()
