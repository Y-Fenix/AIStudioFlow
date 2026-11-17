#!/usr/bin/env python3
"""Check four coverage dimensions and case mappings; never infer business pass/fail."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import validate_source_coverage as sources


TOPICS = {
    "requirements": {"rules", "data_presentation"},
    "coupling": {"shared_state", "event_order", "config_reward"},
    "boundary": {"values", "conditions", "time_state", "interruptions"},
    "upgrade": {"baseline", "migration", "reentry_isolation"},
}
require = sources.require
nonempty = sources.nonempty


def strings(value, context, allow_empty=False):
    require(isinstance(value, list) and (allow_empty or value)
            and all(nonempty(x) for x in value), f"{context}: string list required")
    require(len(value) == len(set(value)), f"{context}: duplicates")
    return set(value)


def validate(coverage, manifest, source_ledger):
    """Validate explicit design records only; source evidence is checked by the CLI."""
    require(coverage.get("schema_version") == 1, "coverage schema_version must be 1")
    require(manifest.get("schema_version") == 1, "input schema_version must be 1")
    selection = strings(coverage.get("selected_source_ids"), "coverage selection")
    require(selection == strings(manifest.get("selected_source_ids"), "input selection")
            == strings(source_ledger.get("selected_source_ids"), "source selection"),
            "selected_source_ids mismatch")
    cases = sources.unique(manifest.get("cases"), "key", "input cases")
    rules = sources.unique(source_ledger.get("rules"), "id", "source rules", allow_empty=True)
    items = sources.unique(coverage.get("items"), "id", "coverage items", allow_empty=True)
    checks = coverage.get("checks")
    require(isinstance(checks, list), "checks: list required")
    gaps, linked_cases, linked_rules, reviewed_items = [], set(), set(), set()
    counts = {dim: Counter() for dim in TOPICS}
    for key, item in items.items():
        dim = item.get("dimension")
        require(dim in TOPICS, f"{key}: invalid dimension")
        require(nonempty(item.get("basis")), f"{key}: basis required")
        state = item.get("status")
        require(state in {"covered", "partial", "missing", "ambiguous"}, f"{key}: invalid status")
        counts[dim][state] += 1
        mapped = strings(item.get("case_keys"), f"{key}: case_keys", allow_empty=state != "covered")
        require(mapped <= cases.keys(), f"{key}: unknown case key")
        linked_cases.update(mapped)
        if state != "covered":
            require(nonempty(item.get("reason")), f"{key}: unresolved reason required")
            gaps.append(f"{key}: {state}: {item['reason']}")
        else:
            scenario = item.get("scenario")
            require(isinstance(scenario, dict), f"{key}: scenario required")
            for field in ("input", "sequence", "expected"):
                require(nonempty(scenario.get(field)), f"{key}: scenario.{field} required")
        if dim == "requirements":
            refs = strings(item.get("rule_ids"), f"{key}: rule_ids")
            require(refs <= rules.keys(), f"{key}: unknown source rule")
            linked_rules.update(refs)
            for ref in refs:
                rule = rules[ref]
                require(rule.get("state") != "excluded", f"{key}: excluded rule must not be counted")
                if state == "covered":
                    require(rule.get("state") == "covered", f"{key}: source rule is not covered")
                    rule_cases = strings(rule.get("case_keys"), f"{ref}: case_keys")
                    require(rule_cases <= mapped, f"{key}: missing source rule case mapping")
        if dim == "coupling" and state == "covered":
            path = item.get("path")
            require(isinstance(path, list) and len(path) >= 2 and all(nonempty(x) for x in path)
                    and len(set(path)) >= 2, f"{key}: at least two distinct coupling nodes required")
        if dim == "upgrade" and state == "covered":
            for field in ("from_version", "old_state"):
                require(nonempty(item.get(field)), f"{key}: {field} required")
    reviewed = set()
    for check in checks:
        require(isinstance(check, dict), "check: object required")
        dim, topic = check.get("dimension"), check.get("topic")
        require(dim in TOPICS and topic in TOPICS[dim], "check: invalid dimension/topic")
        pair = (dim, topic)
        require(pair not in reviewed, f"{pair}: duplicate topic check")
        reviewed.add(pair)
        state = check.get("status")
        require(state in {"applicable", "not_applicable", "unknown"}, f"{pair}: invalid status")
        require(nonempty(check.get("reason")), f"{pair}: basis/reason required")
        refs = strings(check.get("item_ids"), f"{pair}: item_ids", allow_empty=state != "applicable")
        require(refs <= items.keys(), f"{pair}: unknown item")
        require(all(items[ref]["dimension"] == dim for ref in refs), f"{pair}: item dimension mismatch")
        reviewed_items.update(refs)
        if state == "not_applicable":
            require(not refs, f"{pair}: not_applicable must not link items")
            counts[dim]["not_applicable_topics"] += 1
        elif state == "unknown":
            gaps.append(f"{dim}/{topic}: applicability unknown: {check['reason']}")
        elif not any(items[ref]["status"] == "covered" for ref in refs):
            gaps.append(f"{dim}/{topic}: no covered design item")
    expected_topics = {(dim, topic) for dim, topics in TOPICS.items() for topic in topics}
    require(reviewed == expected_topics, f"missing topic checks: {sorted(expected_topics - reviewed)}")
    require(reviewed_items == items.keys(), f"unreviewed items: {sorted(items.keys() - reviewed_items)}")
    for ref, rule in rules.items():
        if rule.get("state") != "excluded" and ref not in linked_rules:
            gaps.append(f"{ref}: source rule has no requirements item")
    for key in sorted(cases.keys() - linked_cases):
        gaps.append(f"{key}: case has no design item")
    return {"schema_version": 1, "status": "partial" if gaps else "complete",
            "dimensions": {dim: {"total": sum(counter[s] for s in
                            ("covered", "partial", "missing", "ambiguous")), **dict(counter)}
                           for dim, counter in counts.items()},
            "case_count": len(cases), "source_rule_count": len(rules), "gaps": gaps,
            "meaning": "Explicit inventory and mapping checks only; not proof of semantic completeness or product correctness."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("coverage", "input", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    try:
        paths = [args.coverage.resolve(), args.input.resolve()]
        coverage, manifest = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        root = args.input.resolve().parent
        source_path = sources.artifact(manifest.get("source_coverage"), root, "source_coverage")
        require(args.output.resolve() not in paths + [source_path.resolve()], "output must not overwrite inputs")
        ledger = json.loads(source_path.read_text(encoding="utf-8"))
        source_result = sources.validate_coverage(ledger, [c["key"] for c in manifest["cases"]], root)
        result = validate(coverage, manifest, ledger)
        result["gaps"].extend("source: " + gap for gap in source_result["gaps"])
        result["status"] = "partial" if result["gaps"] else "complete"
        result["bindings"] = {"input_sha256": hashlib.sha256(paths[1].read_bytes()).hexdigest(),
                              "coverage_sha256": hashlib.sha256(paths[0].read_bytes()).hexdigest(),
                              "source_sha256": manifest["source_coverage"]["sha256"]}
        require(not result["gaps"] or args.allow_partial,
                "coverage incomplete: " + "; ".join(result["gaps"]))
        require(result["status"] == "complete" or manifest.get("report_stage") == "partial",
                "partial coverage requires input report_stage=partial")
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"coverage validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
