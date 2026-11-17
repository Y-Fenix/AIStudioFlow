#!/usr/bin/env python3
"""Validate review evidence and derive report results; never execute reviewed files."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import validate_source_coverage as source_coverage
import cross_repo


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def fields(item, names, context):
    for name in names:
        require(nonempty(item.get(name)), f"{context}: missing {name}")


def index(items, field, context):
    require(isinstance(items, list) and items, f"{context}: nonempty list required")
    result = {}
    for item in items:
        require(isinstance(item, dict), f"{context}: object required")
        key = item.get(field)
        require(nonempty(key) and key not in result, f"{context}: missing/duplicate {field}: {key}")
        result[key] = item
    return result


def fingerprint(cells):
    return hashlib.sha256(json.dumps(cells, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def file_path(value, root):
    require(nonempty(value), "evidence: path required")
    path = Path(value)
    return path if path.is_absolute() else root / path


def check_evidence(items, root, baseline):
    if items == []:
        return {}
    evidence = index(items, "id", "evidence")
    for key, entry in evidence.items():
        kind = entry.get("kind")
        require(kind in {"source", "requirement", "run", "observation"}, f"{key}: invalid kind")
        path = file_path(entry.get("path"), root)
        require(path.is_file(), f"{key}: missing evidence file {path}")
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == entry.get("sha256"), f"{key}: stale/missing sha256")
        fields(entry, ["locator"], key)
        if kind in {"source", "run", "observation"}:
            require(entry.get("baseline") == baseline, f"{key}: baseline mismatch")
        if kind == "source":
            line = entry.get("line")
            require(type(line) is int and 1 <= line <= len(raw.splitlines()), f"{key}: invalid source line")
        if kind == "run":
            command = entry.get("command")
            require(isinstance(command, list) and command and all(nonempty(x) for x in command),
                    f"{key}: command must be actual argv")
            fields(entry, ["cwd", "runner", "run_id"], key)
            for name in ["exit_code", "discovered", "passed", "failed", "errors", "skipped"]:
                require(type(entry.get(name)) is int, f"{key}: invalid {name}")
            counts = [entry[n] for n in ["passed", "failed", "errors", "skipped"]]
            require(min(counts) >= 0 and entry["discovered"] > 0, f"{key}: zero/invalid test counts")
            require(sum(counts) == entry["discovered"], f"{key}: inconsistent test counts")
            require(entry["exit_code"] == 0 or entry["failed"] + entry["errors"] > 0,
                    f"{key}: abnormal exit cannot support test results")
            results = entry.get("results")
            require(isinstance(results, dict) and results, f"{key}: assertion-to-test results required")
            require(all(v in {"passed", "failed", "skipped"} for v in results.values()),
                    f"{key}: invalid mapped test result")
            for mapped, count in [("passed", "passed"), ("failed", "failed"), ("skipped", "skipped")]:
                require(mapped not in results.values() or entry[count] > 0,
                        f"{key}: mapped result contradicts test counts")
    return evidence


def check_blocker(assertion, context):
    blocker = assertion.get("blocker")
    require(isinstance(blocker, dict), f"{context}: blocker required")
    fields(blocker, ["variable", "why_local_insufficient", "next_action", "owner"], context)
    kind = blocker.get("kind")
    require(kind in {"external", "requirement", "materials", "environment", "automation", "seam"},
            f"{context}: invalid blocker kind")
    if kind == "external":
        require(assertion["domain"] == "external", f"{context}: local assertion cannot transfer to blackbox")
        fields(blocker, ["preparation", "steps", "observation"], context)
    if kind in {"environment", "automation", "seam"}:
        require(assertion["domain"] == "local", f"{context}: local blocker expected")
        fields(blocker, ["static_gap", "cannot_resolve_locally"], context)
        attempts = index(blocker.get("attempts"), "strategy", context + " attempts")
        require({"static_trace", "fixture", "existing_runner"} <= attempts.keys(),
                f"{context}: static/fixture/runner attempts required before deferral")
        for attempt in attempts.values():
            require(attempt.get("status") in {"attempted", "unavailable"}, f"{context}: invalid attempt")
            fields(attempt, ["result"], context)
    if kind in {"materials", "requirement"}:
        fields(blocker, ["searched", "missing_or_conflict"], context)


def check_assertion(a, original, evidence, context):
    require(a.get("text") == original["text"], f"{context}: changed assertion text")
    require(a.get("domain") in {"local", "external"}, f"{context}: invalid domain")
    verdict, method = a.get("verdict"), a.get("method")
    require(verdict in {"pass", "fail", "unresolved", "obsolete"}, f"{context}: invalid verdict")
    fields(a, ["reason"], context)
    refs = a.get("evidence", [])
    require(isinstance(refs, list) and all(isinstance(x, str) and x in evidence for x in refs),
            f"{context}: dangling/invalid evidence reference")
    entries = [evidence[x] for x in refs]
    kinds = {x["kind"] for x in entries}
    if verdict in {"pass", "fail"}:
        fields(a, ["input", "expected", "actual"], context)
        require("requirement" in kinds, f"{context}: missing independent expectation source")
        if a["domain"] == "external":
            require(method == "observed" and "observation" in kinds,
                    f"{context}: external result requires actual observation")
        else:
            require(method in {"static", "automated"}, f"{context}: invalid local proof")
            require("source" in kinds, f"{context}: missing actual production source")
            if method == "automated":
                expected_status = "passed" if verdict == "pass" else "failed"
                runs = [e for e in entries if e["kind"] == "run"]
                require(any(e["results"].get(context) == expected_status for e in runs),
                        f"{context}: missing mapped actual run result")
        if verdict == "fail":
            fields(a, ["reachability", "steps"], context)
    elif verdict == "unresolved":
        require(method == "none", f"{context}: unresolved cannot claim proof")
        check_blocker(a, context)
    else:
        require(method == "none" and "requirement" in kinds, f"{context}: obsolete requires authority")
        fields(a, ["replacement"], context)
    if a["domain"] == "external":
        fields(a, ["external_variable", "why_local_insufficient"], context)


def aggregate(assertions):
    if any(a["verdict"] == "fail" for a in assertions):
        return "测试不通过"
    if any(a["verdict"] == "obsolete" for a in assertions):
        return "用例需更新"
    pending = [a for a in assertions if a["verdict"] == "unresolved"]
    for kind, status in [("requirement", "需求待确认"), ("materials", "证据不足"),
                         ("seam", "需开发补测试接缝"), ("environment", "需自动化验证"),
                         ("automation", "需自动化验证"), ("external", "需黑盒验证")]:
        if any(a["blocker"]["kind"] == kind for a in pending):
            return status
    if not assertions:
        return "需黑盒验证"
    if all(a["method"] == "automated" for a in assertions):
        return "测试通过（自动化）"
    if all(a["method"] == "observed" for a in assertions):
        return "测试通过（真实环境）"
    if any(a["method"] == "observed" for a in assertions):
        return "测试通过（混合证据）"
    return "测试通过（静态）"


def validate(manifest, review, root):
    require(manifest.get("schema_version") == review.get("schema_version") == 1, "schema_version must be 1")
    require(review.get("scope") in {"code", "full"}, "scope must be code or full")
    require(nonempty(review.get("baseline")), "baseline required")
    original = index(manifest.get("cases"), "key", "input cases")
    reviewed = index(review.get("cases"), "key", "review cases")
    require(list(original) == list(reviewed), "missing/extra/reordered case keys")
    try:
        coverage = source_coverage.validate_binding(manifest, review, root)
    except ValueError as exc:
        raise Invalid(str(exc)) from exc
    evidence = check_evidence(review.get("evidence"), root, review["baseline"])
    cross = cross_repo.binding(manifest, review, root)
    output, totals = [], Counter()
    external_count = local_pending = 0
    for key, case in original.items():
        cells = case.get("cells")
        require(isinstance(cells, list) and len(cells) == 6 and all(isinstance(x, str) for x in cells),
                f"{key}: original six text cells required")
        item = reviewed[key]
        digest = fingerprint(cells)
        require(item.get("input_sha256") == digest, f"{key}: original six cells changed")
        source_assertions = index(case.get("assertions"), "id", key + " input assertions")
        assertions = index(item.get("assertions"), "id", key + " review assertions")
        require(list(source_assertions) == list(assertions), f"{key}: missing/extra/reordered assertions")
        for aid, assertion in assertions.items():
            fields(source_assertions[aid], ["text"], key)
            check_assertion(assertion, source_assertions[aid], evidence, f"{key}/{aid}")
            targets = source_assertions[aid].get('cross_repo_targets')
            if targets is not None:
                require(cross is not None and isinstance(targets, list) and targets,
                        f'{key}/{aid}: cross_repo binding and targets required')
                require(all(t in cross['assertions'] for t in targets), f'{key}/{aid}: unknown cross_repo target')
                states = {cross['assertions'][t] for t in targets}
                expected = 'fail' if 'fail' in states else 'unresolved' if states & {'blocked', 'unreviewed'} else 'pass'
                require(assertion['domain'] == 'local' and assertion['verdict'] == expected,
                        f'{key}/{aid}: cross_repo verdict mismatch')
        values = list(assertions.values())
        local = [a for a in values if a["domain"] == "local"]
        external = [a for a in values if a["domain"] == "external"]
        selected = local if review["scope"] == "code" and local else values
        status = aggregate(selected)
        if "result" in item:
            require(item["result"] == status, f"{key}: declared result disagrees with evidence")
        residual = [a for a in external if a["verdict"] != "pass"]
        external_count += len(residual)
        local_pending += sum(a["verdict"] == "unresolved" for a in local)
        totals[status] += 1
        output.append({"key": key, "input_sha256": digest, "result": status,
                       "external_residual_ids": [a["id"] for a in residual],
                       "external_failure_ids": [a["id"] for a in external if a["verdict"] == "fail"]})
    return {"schema_version": 1, "scope": review["scope"], "baseline": review["baseline"],
            "root": str(root.resolve()), "report_stage": manifest.get("report_stage", "final"),
            "manifest_sha256": source_coverage.digest(manifest),
            "review_sha256": source_coverage.digest(review), "source_coverage": coverage,
            "cross_repo": cross,
            "validation": "passed", "meaning": "integrity checks only; not product acceptance",
            "input_cases": len(original), "counts": dict(totals),
            "local_unresolved_assertions": local_pending, "external_residual_assertions": external_count,
            "cases": output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="New validation summary consumed by the report generator")
    args = parser.parse_args()
    try:
        require(args.root.is_dir(), "project root does not exist")
        result = validate(json.loads(args.input.read_text(encoding="utf-8")),
                          json.loads(args.review.read_text(encoding="utf-8")), args.root)
        if args.output:
            require(args.output.resolve() not in {args.input.resolve(), args.review.resolve()},
                    "output cannot overwrite input/review")
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (Invalid, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"REPORT_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
