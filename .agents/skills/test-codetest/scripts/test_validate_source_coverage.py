#!/usr/bin/env python3
"""Contract tests: inventory omissions, stale reads, and rule-to-case gaps."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import validate_source_coverage as gate


class SourceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.png = self.put("image.png", base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6"
            "nX8AAAAASUVORK5CYII="))
        self.log = self.put("inspection.json", b'{"tool":"view_image","result":"viewed"}')
        self.snapshot = self.put("doc.json", json.dumps({"ok": True, "data": {"document": {
            "content": '<p>到期不可领取</p><img id="a" src="token" alt="自动摘要"/>',
            "revision_id": 1}}}).encode())
        self.case_keys = ["测试用例!2"]
        inventory = gate.scan(self.root / "doc.json")["media"]
        self.source = {"id": "req", "title": "活动", "origin": "https://example.invalid/doc",
                       "version": "1", "accessed_at": "2026-11-03T10:00:00+08:00",
                       "snapshot": self.snapshot, "state": "read",
                       "closure": {"complete": True, "note": "已核对完整响应，无分页或截断"},
                       "inspection": self.inspection("text", self.snapshot),
                       "media": [{**inventory[0], "state": "read", "artifact": self.png,
                                  "inspection": self.inspection("image", self.png)}]}
        self.ledger = {"schema_version": 1, "selected_source_ids": ["req"],
                       "sources": [self.source], "rules": [
                           {"id": "rule", "source_id": "req", "locator": "正文及图a",
                            "text": "到期不可领取", "media_keys": [inventory[0]["key"]],
                            "state": "covered", "case_keys": self.case_keys.copy()}]}

    def put(self, name, raw):
        (self.root / name).write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}

    def inspection(self, method, artifact):
        return {"method": method, "artifact_sha256": artifact["sha256"],
                "evidence": self.log, "locator": "实际工具读取回执", "findings": "到期禁领，按钮灰态"}

    def check(self):
        return gate.validate_coverage(self.ledger, self.case_keys, self.root)

    def test_read_image_mapped_to_existing_case_is_complete(self):
        result = self.check()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["media"], {"image": {"total": 1, "read": 1}})

    def test_deleted_or_duplicate_media_is_rejected(self):
        original = copy.deepcopy(self.source["media"])
        for media in [[], original * 2]:
            self.source["media"] = media
            with self.assertRaises(ValueError):
                self.check()

    def test_unread_media_cannot_be_complete_even_with_alt_summary(self):
        self.source["media"][0].update(state="unread", gap="原图未读取；alt不作为证据")
        self.assertEqual(self.check()["status"], "partial")

    def test_alt_ocr_and_download_are_not_visual_inspection(self):
        for method in ["alt", "ocr", "download"]:
            self.source["media"][0]["inspection"]["method"] = method
            with self.assertRaises(ValueError):
                self.check()

    def test_missing_or_stale_read_receipt_is_rejected(self):
        self.source["media"][0]["inspection"]["artifact_sha256"] = "old"
        with self.assertRaises(ValueError):
            self.check()
        self.source["media"][0]["inspection"] = self.inspection("image", self.png)
        (self.root / "inspection.json").unlink()
        with self.assertRaises(ValueError):
            self.check()

    def test_changed_revision_and_snapshot_hash_are_rejected(self):
        self.source["version"] = "2"
        with self.assertRaises(ValueError):
            self.check()
        self.source["version"] = "1"
        (self.root / "doc.json").write_text("changed")
        with self.assertRaises(ValueError):
            self.check()

    def test_read_but_unmapped_rule_is_partial(self):
        self.ledger["rules"][0].update(state="uncovered", case_keys=[], reason="缺少对应测试")
        self.assertEqual(self.check()["status"], "partial")

    def test_fabricated_case_key_is_rejected(self):
        self.ledger["rules"][0]["case_keys"] = ["不存在!9"]
        with self.assertRaises(ValueError):
            self.check()

    def test_missing_selected_source_is_rejected(self):
        self.ledger["selected_source_ids"].append("lost")
        with self.assertRaises(ValueError):
            self.check()

    def test_decorative_requires_read_and_reason_but_no_extra_case(self):
        self.ledger["rules"][0]["media_keys"] = []
        self.assertEqual(self.check()["status"], "partial")
        self.source["media"][0]["no_rules_reason"] = "已查看，只有重复背景装饰"
        self.assertEqual(self.check()["status"], "complete")
        self.assertEqual(len(self.case_keys), 1)

    def test_text_only_source_still_has_explicit_inventory(self):
        self.source["snapshot"] = self.put("text.md", "到期不可领取".encode())
        self.source["inspection"] = self.inspection("text", self.source["snapshot"])
        self.source["media"] = []
        self.ledger["rules"][0]["media_keys"] = []
        self.assertEqual(self.check()["media"], {})
        del self.source["media"]
        with self.assertRaises(ValueError):
            self.check()

    def test_video_needs_entire_timeline_not_one_frame(self):
        self.source["snapshot"] = self.put("video.xml", b'<source mime="video/mp4" token="v"/>')
        self.source["inspection"] = self.inspection("text", self.source["snapshot"])
        item = gate.scan(self.root / "video.xml")["media"][0]
        video = self.put("v.mp4", b"\x00\x00\x00\x18ftypmp42")
        inspect = self.inspection("video", video)
        inspect.update(duration_seconds=10, intervals=[[0, 1]])
        self.source["media"] = [{**item, "state": "read", "artifact": video, "inspection": inspect}]
        self.ledger["rules"][0]["media_keys"] = [item["key"]]
        with self.assertRaises(ValueError):
            self.check()
        inspect["intervals"] = [[0, 5], [5, 10]]
        self.assertEqual(self.check()["status"], "complete")

    def test_scan_docx_includes_header_relationship_and_embedded_object(self):
        path = self.root / "test.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/_rels/header1.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/></Relationships>')
            z.writestr("word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="embeddings/a.bin"/></Relationships>')
        self.assertEqual({x["kind"] for x in gate.scan(path)["media"]}, {"image", "attachment"})

    def test_json_excerpt_is_not_full_source(self):
        self.source["snapshot"] = self.put("excerpt.json", b'{"ok":true,"data":{"document":{"content":"<excerpt>partial</excerpt>"}}}')
        self.source["inspection"] = self.inspection("text", self.source["snapshot"])
        self.source["media"] = []
        self.ledger["rules"][0]["media_keys"] = []
        self.assertEqual(self.check()["status"], "partial")

    def test_scan_markdown_inline_full_collapsed_and_shortcut_images(self):
        text = ('![inline](a.png) ![full][a] ![collapsed][] ![shortcut]\n'
                '[a]: b.png\n[collapsed]: c.png\n[shortcut]: d.png\n')
        self.put("all.md", text.encode())
        self.assertEqual([x["ref"] for x in gate.scan(self.root / "all.md")["media"]],
                         ["a.png", "b.png", "c.png", "d.png"])

    def test_scan_markdown_inside_json_response_is_not_lost(self):
        self.put("markdown.json", json.dumps({"document": {"content": "![rule](rule.png)"}}).encode())
        self.assertEqual(gate.scan(self.root / "markdown.json")["media"][0]["ref"], "rule.png")

    def test_source_image_mime_requires_image_inspection(self):
        self.put("media.xml", b'<source mime="image/png" token="i"/>')
        self.assertEqual(gate.scan(self.root / "media.xml")["media"][0]["kind"], "image")

    def test_video_container_with_nested_source_can_be_inventoried(self):
        self.put("player.html", b'<video controls><source src="v.mp4" type="video/mp4"></video>')
        self.assertEqual([(x["kind"], x["ref"]) for x in gate.scan(self.root / "player.html")["media"]],
                         [("video", "v.mp4")])

    def test_markdown_reference_labels_ignore_case_and_whitespace(self):
        self.put("labels.md", b'![rule][A  B]\n[a b]: image.png\n')
        self.assertEqual(gate.scan(self.root / "labels.md")["media"][0]["ref"], "image.png")

    def test_docx_generic_media_relationship_is_not_lost(self):
        path = self.root / "media.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/_rels/document.xml.rels", '<Relationships><Relationship Id="r1" Type="http://schemas.microsoft.com/office/2007/relationships/media" TargetMode="External" Target="clip.mp4"/></Relationships>')
        self.assertEqual(gate.scan(path)["media"][0]["kind"], "video")

    def test_video_type_cannot_hide_as_generic_attachment(self):
        for content in ['<source src="clip.mp4"/>', '<file mime="video/mp4" token="clip"/>',
                        '<object data="clip.mp4" type="video/mp4"></object>']:
            self.put("kind.xml", content.encode())
            self.assertEqual(gate.scan(self.root / "kind.xml")["media"][0]["kind"], "video")

    def test_empty_video_container_fails_closed(self):
        self.put("empty.html", b'<video controls></video>')
        with self.assertRaises(ValueError):
            gate.scan(self.root / "empty.html")

    def test_text_file_cannot_be_image_artifact(self):
        item = self.source["media"][0]
        item["artifact"] = self.put("fake.png", b"not an image")
        item["inspection"] = self.inspection("image", item["artifact"])
        with self.assertRaises(ValueError):
            self.check()

    def test_independent_selected_scope_must_match_ledger(self):
        binding = self.put("coverage.json", json.dumps(self.ledger).encode())
        manifest = {"cases": [{"key": self.case_keys[0]}], "source_coverage": binding,
                    "selected_source_ids": ["req", "missing"]}
        review = {"source_coverage": binding}
        with self.assertRaisesRegex(ValueError, "selected_source_ids"):
            gate.validate_binding(manifest, review, self.root)

    def test_cli_rejects_partial_by_default_and_does_not_overwrite(self):
        self.source["media"][0].update(state="unread", gap="未读原图")
        ledger = self.root / "coverage.json"
        ledger.write_text(json.dumps(self.ledger))
        manifest = self.root / "input.json"
        manifest.write_text(json.dumps({"selected_source_ids": ["req"],
                                        "cases": [{"key": self.case_keys[0]}]}))
        output = self.root / "summary.json"
        command = [sys.executable, gate.__file__, "check", "--ledger", str(ledger), "--input", str(manifest),
                   "--root", str(self.root), "--output", str(output)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(first.returncode, 0)
        self.assertFalse(output.exists())
        second = subprocess.run(command + ["--allow-partial"], capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(output.read_text())["status"], "partial")
        self.assertNotEqual(subprocess.run(command + ["--allow-partial"], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
