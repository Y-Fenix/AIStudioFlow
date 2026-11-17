#!/usr/bin/env python3
"""Inventory source media and validate read receipts/rule mappings; no network or execution."""
import argparse
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import urlsplit


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def artifact(record, root, context):
    require(isinstance(record, dict) and nonempty(record.get("path")), f"{context}: file reference required")
    path = Path(record["path"])
    path = path if path.is_absolute() else root / path
    require(path.is_file(), f"{context}: missing file {path}")
    require(hashlib.sha256(path.read_bytes()).hexdigest() == record.get("sha256"),
            f"{context}: stale/missing sha256")
    return path


def unique(items, field, context, allow_empty=False):
    require(isinstance(items, list) and (allow_empty or items), f"{context}: list required")
    out = {}
    for item in items:
        require(isinstance(item, dict), f"{context}: object required")
        key = item.get(field)
        require(nonempty(key) and key not in out, f"{context}: missing/duplicate {field}")
        out[key] = item
    return out


def media_hint(ref, mime=""):
    mime = mime.lower()
    for kind in ("image", "video", "audio"):
        if mime.startswith(kind + "/"):
            return kind
    ext = Path(urlsplit(ref).path).suffix.lower()
    for kind, extensions in {
            "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg", ".avif"},
            "video": {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"},
            "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}}.items():
        if ext in extensions:
            return kind
    return None


def image_signature(path):
    with path.open("rb") as stream:
        head = stream.read(4096)
    return (head.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM",
                             b"II*\x00", b"MM\x00*")) or
            head[:4] == b"RIFF" and head[8:12] == b"WEBP" or
            head[4:8] == b"ftyp" and head[8:12] in {b"avif", b"avis"} or
            re.search(br"<svg(?:\s|>)", head) is not None)


class MediaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.media = []
        self.excerpt = False
        self.containers = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in {"video", "audio"} and self.containers:
            opened, count = self.containers.pop()
            require(opened == tag and len(self.media) > count, f"{tag}: no media source found")

    def close(self):
        super().close()
        require(not self.containers, "unclosed media container")

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"excerpt", "truncated"}:
            self.excerpt = True
        ref = next((attrs[x] for x in ("src", "token", "url", "data", "id") if attrs.get(x)), "")
        if tag in {"video", "audio"}:
            self.containers.append((tag, len(self.media)))
            if not ref:
                return
        kind = {"img": "image", "image": "image", "whiteboard": "whiteboard",
                "sheet": "table", "bitable": "table", "iframe": "embed",
                "attachment": "attachment", "file": "attachment", "object": "attachment",
                "embed": "embed"}.get(tag)
        if kind or tag in {"video", "audio", "source"}:
            kind = media_hint(ref, attrs.get("mime", attrs.get("type", ""))) or (
                tag if tag in {"video", "audio"} else (
                    self.containers[-1][0] if tag == "source" and self.containers else kind or "attachment"))
        if kind:
            require(nonempty(ref), f"{tag}: missing media reference; inspect raw block")
            self.media.append({"kind": kind, "ref": ref,
                               "locator": f"{tag} id={attrs.get('id', '')} line={self.getpos()[0]}"})


def scan(path):
    """Deterministic inventory of raw snapshots; never mark an asset read."""
    path = Path(path)
    raw = path.read_bytes()
    version = None
    if path.suffix.lower() == ".docx":
        media = []
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not name.endswith(".rels"):
                    continue
                for rel in ET.fromstring(archive.read(name)):
                    typ = rel.attrib.get("Type", "").rsplit("/", 1)[-1]
                    kind = {"image": "image", "video": "video", "audio": "audio",
                            "oleObject": "attachment", "package": "attachment",
                            "chart": "table", "diagramData": "whiteboard",
                            "aFChunk": "embed", "media": "attachment"}.get(typ)
                    if kind:
                        kind = media_hint(rel.attrib.get("Target", "")) or kind
                        media.append({"kind": kind, "ref": rel.attrib.get("Target", ""),
                                      "locator": f"{name}#{rel.attrib.get('Id', '')}"})
        fmt, closed = "docx", True
    else:
        supported = {".json", ".xml", ".html", ".htm", ".md", ".markdown", ".txt"}
        if path.suffix.lower() not in supported:
            return {"format": "manual", "version": None, "closed": None, "media": None}
        content = raw.decode("utf-8-sig")
        fmt = path.suffix.lower()[1:]
        if fmt == "json":
            data = json.loads(content)
            require(isinstance(data, dict) and data.get("ok") is not False, "failed source response")
            document = data.get("data", {}).get("document", data.get("document"))
            require(isinstance(document, dict) and isinstance(document.get("content"), str),
                    "JSON snapshot must contain document.content; use manual export for other data")
            content = document["content"]
            version = document.get("revision_id")
        parser = MediaParser()
        parser.feed(content)
        parser.close()
        media = parser.media
        # Feishu JSON and mixed HTML/XML can contain Markdown too.
        label_key = lambda value: " ".join(value.split()).casefold()
        definitions = {}
        for label, ref in re.findall(r"(?m)^\s*\[([^\]]+)\]:\s*<?([^\s>]+)>?", content):
            definitions.setdefault(label_key(label), ref)
        pattern = r"!\[([^\]]*)\](?:\(\s*(<[^>]+>|[^\s)]+)(?:[^)]*)\)|\[([^\]]*)\])?"
        for match in re.finditer(pattern, content):
            ref = match.group(2)
            if ref is None:
                label = label_key(match.group(3) or match.group(1))
                require(label in definitions, f"unresolved image reference: {label}")
                ref = definitions[label]
            media.append({"kind": "image", "ref": ref.strip("<>"),
                          "locator": f"markdown offset={match.start()}"})
        closed = not parser.excerpt
    for i, item in enumerate(media, 1):
        item["key"] = f"media:{i}"
    return {"format": fmt, "version": version, "closed": closed, "media": media}


def inspect(record, target, root, methods, context):
    require(isinstance(record, dict) and record.get("method") in methods,
            f"{context}: actual inspection method required; alt/OCR/download alone is insufficient")
    require(record.get("artifact_sha256") == target.get("sha256"), f"{context}: stale read receipt")
    for name in ("locator", "findings"):
        require(nonempty(record.get(name)), f"{context}: missing {name}")
    artifact(record.get("evidence"), root, context + " inspection evidence")
    if record["method"] == "video":
        duration = record.get("duration_seconds")
        require(type(duration) in (int, float) and math.isfinite(duration) and duration > 0,
                f"{context}: actual video duration required")
        intervals = record.get("intervals")
        require(isinstance(intervals, list) and intervals, f"{context}: inspected video intervals required")
        for interval in intervals:
            require(isinstance(interval, list) and len(interval) == 2 and all(
                type(v) in (int, float) and math.isfinite(v) for v in interval),
                f"{context}: invalid video interval")
            require(0 <= interval[0] < interval[1] <= duration, f"{context}: invalid video interval")
        end = 0
        for start, stop in sorted(intervals):
            require(start <= end + 0.001, f"{context}: video timeline has an unread gap")
            end = max(end, stop)
        require(end >= duration - 0.001, f"{context}: video timeline not fully inspected")


def validate_coverage(ledger, case_keys, root):
    require(ledger.get("schema_version") == 1, "source coverage schema_version must be 1")
    selected = ledger.get("selected_source_ids")
    require(isinstance(selected, list) and selected and all(nonempty(x) for x in selected) and
            len(selected) == len(set(selected)), "selected_source_ids: explicit unique selection required")
    sources = unique(ledger.get("sources"), "id", "sources")
    require(set(selected) <= sources.keys(), "selected source missing from sources")
    rules = unique(ledger.get("rules"), "id", "rules", allow_empty=True)
    require(len(case_keys) == len(set(case_keys)), "duplicate input case key")
    gaps, media_counts, media_read, inventories = [], Counter(), Counter(), {}
    linked_cases = set()
    rule_counts = Counter()
    for rid, rule in rules.items():
        sid = rule.get("source_id")
        require(sid in sources, f"{rid}: unknown source_id")
        for name in ("locator", "text"):
            require(nonempty(rule.get(name)), f"{rid}: missing {name}")
        refs = rule.get("media_keys")
        require(isinstance(refs, list) and all(nonempty(x) for x in refs) and len(refs) == len(set(refs)),
                f"{rid}: explicit unique media_keys required (empty for text)")
        state = rule.get("state")
        require(state in {"covered", "uncovered", "ambiguous", "excluded"}, f"{rid}: invalid rule state")
        keys = rule.get("case_keys", [])
        require(isinstance(keys, list) and all(nonempty(x) for x in keys) and len(keys) == len(set(keys)),
                f"{rid}: invalid case_keys")
        require(set(keys) <= set(case_keys), f"{rid}: rule links unknown input case")
        if state == "covered":
            require(keys, f"{rid}: covered rule has no case")
            linked_cases.update(keys)
        else:
            require(nonempty(rule.get("reason")), f"{rid}: reason required")
            if state != "excluded":
                gaps.append(f"{sid}/{rid}: {state}: {rule['reason']}")
        rule_counts[state] += 1
    for sid, source in sources.items():
        for name in ("title", "origin", "version", "accessed_at"):
            require(nonempty(source.get(name)), f"{sid}: missing {name}")
        if sid not in selected:
            require(nonempty(source.get("basis")), f"{sid}: dependency/coupling basis required")
        state = source.get("state")
        require(state in {"read", "partial", "unread"}, f"{sid}: invalid source state")
        declared = unique(source.get("media"), "key", sid + " media", allow_empty=True)
        if not source.get("snapshot"):
            require(state != "read" and nonempty(source.get("gap")), f"{sid}: missing snapshot")
            require(not declared, f"{sid}: cannot verify media without raw snapshot")
            gaps.append(f"{sid}: source not inventoried: {source['gap']}")
            inventories[sid] = {}
            continue
        path = artifact(source["snapshot"], root, sid + " snapshot")
        inventory = scan(path)
        if inventory["version"] is not None:
            require(str(inventory["version"]) == source["version"], f"{sid}: source revision mismatch")
        if inventory["media"] is None:
            manual = source.get("manual_inventory")
            require(isinstance(manual, dict), f"{sid}: unsupported format; manual inventory evidence required")
            artifact(manual.get("evidence"), root, sid + " manual inventory")
            require(nonempty(manual.get("method")) and nonempty(manual.get("note")),
                    f"{sid}: manual inventory method/note required")
            expected = unique(manual.get("media"), "key", sid + " manual media", allow_empty=True)
        else:
            expected = unique(inventory["media"], "key", sid + " scanned media", allow_empty=True)
        require(set(expected) == set(declared), f"{sid}: raw inventory and media keys differ (missing/extra)")
        inventories[sid] = declared
        closure = source.get("closure", {})
        require(type(closure.get("complete")) is bool and nonempty(closure.get("note")),
                f"{sid}: explicit pagination/selection closure required")
        if not closure["complete"] or inventory["closed"] is False:
            gaps.append(f"{sid}: source scope incomplete: {closure['note']}")
        if state == "read":
            inspect(source.get("inspection"), source["snapshot"], root, {"text", "document"}, sid)
        else:
            require(nonempty(source.get("gap")), f"{sid}: partial/unread source needs impact")
            gaps.append(f"{sid}: {state}: {source['gap']}")
        for key, item in declared.items():
            ctx = f"{sid}/{key}"
            require(all(item.get(n) == expected[key].get(n) and nonempty(item.get(n))
                        for n in ("kind", "ref", "locator")), f"{ctx}: media reference/position changed")
            kind = item["kind"]
            media_counts[kind] += 1
            require(item.get("state") in {"read", "partial", "unread"}, f"{ctx}: invalid media state")
            if item["state"] == "read":
                asset = artifact(item.get("artifact"), root, ctx + " original asset/export")
                if item.get("inspection", {}).get("method") == "image":
                    require(image_signature(asset), f"{ctx}: artifact is not a supported image; inspect actual type")
                hint = media_hint(item["ref"]) or media_hint(str(asset))
                if hint in {"video", "audio"}:
                    require(item.get("inspection", {}).get("method") == hint,
                            f"{ctx}: {hint} cannot be inspected as another media type")
                methods = {"image": {"image"}, "whiteboard": {"image", "document"},
                           "video": {"video"}, "audio": {"audio"}, "table": {"data", "document"},
                           "embed": {"document", "data", "image"},
                           "attachment": {"document", "data", "image", "video", "audio"}}
                require(kind in methods, f"{ctx}: unsupported media kind")
                inspect(item.get("inspection"), item["artifact"], root, methods[kind], ctx)
                media_read[kind] += 1
            else:
                require(nonempty(item.get("gap")), f"{ctx}: unread/partial impact required")
                gaps.append(f"{ctx}: {item['state']}: {item['gap']}")
            mapped = [r for r in rules.values() if r["source_id"] == sid and key in r["media_keys"]]
            if not mapped and not nonempty(item.get("no_rules_reason")):
                gaps.append(f"{ctx}: inspected media has no rule mapping or no-rules basis")
        source_rules = [r for r in rules.values() if r["source_id"] == sid]
        if not source_rules and not nonempty(source.get("no_rules_reason")):
            gaps.append(f"{sid}: no requirement rules or exclusion basis")
    for rid, rule in rules.items():
        require(set(rule["media_keys"]) <= inventories[rule["source_id"]].keys(),
                f"{rid}: rule links unknown media")
    for key in set(case_keys) - linked_cases:
        gaps.append(f"{key}: no covered source rule mapping")
    return {"status": "partial" if gaps else "complete", "selected_sources": len(selected),
            "sources": len(sources), "read_sources": sum(s.get("state") == "read" for s in sources.values()),
            "media": {k: {"total": n, "read": media_read[k]} for k, n in sorted(media_counts.items())},
            "rules": dict(rule_counts), "gaps": gaps,
            "meaning": "inventory/evidence/mapping integrity only; visual understanding still requires review"}


def validate_binding(manifest, review, root):
    stage = manifest.get("report_stage", "final")
    require(stage in {"final", "partial"} and review.get("report_stage", "final") == stage,
            "report_stage mismatch")
    binding = manifest.get("source_coverage")
    require(review.get("source_coverage") == binding, "source_coverage binding mismatch")
    if binding is None:
        require(stage == "partial", "source_coverage required for final report")
        return {"status": "partial", "selected_sources": 0, "sources": 0, "read_sources": 0,
                "media": {}, "rules": {}, "gaps": ["旧表未建立来源/媒体清单；仅审查现有用例，不能声称完整需求覆盖"]}
    path = artifact(binding, root, "source_coverage")
    ledger = json.loads(path.read_text(encoding="utf-8"))
    check_selection(manifest, ledger)
    result = validate_coverage(ledger,
                               [c["key"] for c in manifest["cases"]], root)
    require(stage == "partial" or result["status"] == "complete",
            "source coverage incomplete; finish reads/mappings or explicitly deliver report_stage=partial")
    return {**result, "ledger_sha256": binding["sha256"]}


def check_selection(manifest, ledger):
    selected = manifest.get("selected_source_ids")
    require(isinstance(selected, list) and selected and all(nonempty(x) for x in selected)
            and len(selected) == len(set(selected)), "input selected_source_ids required")
    require(set(selected) == set(ledger.get("selected_source_ids", [])),
            "input/ledger selected_source_ids mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan_cmd = sub.add_parser("scan")
    scan_cmd.add_argument("--snapshot", required=True, type=Path)
    check = sub.add_parser("check")
    for arg in ("ledger", "input", "root"):
        check.add_argument("--" + arg, required=True, type=Path)
    check.add_argument("--allow-partial", action="store_true")
    check.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "scan":
            result = scan(args.snapshot)
        else:
            ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
            manifest = json.loads(args.input.read_text(encoding="utf-8"))
            check_selection(manifest, ledger)
            result = validate_coverage(ledger, [c["key"] for c in manifest["cases"]], args.root)
            require(args.allow_partial or result["status"] == "complete", json.dumps(result, ensure_ascii=False))
            if args.output:
                with args.output.open("x", encoding="utf-8") as stream:
                    json.dump(result, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, zipfile.BadZipFile, ET.ParseError) as exc:
        print(f"SOURCE_COVERAGE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
