#!/usr/bin/env python3
"""Freeze and audit the GagaSort tracking contract against C# source.

The script intentionally performs a bounded static audit. It does not claim
that the SDK received an event, nor that a server accepted its payload.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


HEADERS = [
    "event_label", "event_name", "trigger", "property_name", "property_type",
    "property_description", "remark1", "remark",
]


def clean(value) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ").strip()


def load_xlsx(path: Path) -> list[dict]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise SystemExit("读取埋点 xlsx 需要 openpyxl；请先安装 openpyxl，或直接使用已固化的 tracking-contract.json") from exc
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows or clean(rows[0][1]) != "事件名":
        raise ValueError("埋点表首行不是预期的事件名列")
    current_event = ""
    current_label = ""
    current_trigger = ""
    records: list[dict] = []
    for row in rows[1:]:
        values = list(row[:8]) + [None] * 8
        if clean(values[0]):
            current_label = clean(values[0])
        if clean(values[1]):
            current_event = clean(values[1])
            current_trigger = clean(values[2])
        if not current_event:
            continue
        prop = clean(values[3])
        if not prop and not clean(values[1]):
            continue
        records.append({
            "event_label": current_label,
            "event_name": current_event,
            "trigger": current_trigger,
            "property_name": prop,
            "property_type": clean(values[4]),
            "property_description": clean(values[5]),
            "remark1": clean(values[6]),
            "remark": clean(values[7]),
        })
    return records


def save_contract(records: list[dict], csv_path: Path, json_path: Path, source: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(records)
    groups = []
    for event in dict.fromkeys(row["event_name"] for row in records):
        rows = [row for row in records if row["event_name"] == event]
        groups.append({
            "event_name": event,
            "event_label": rows[0]["event_label"],
            "trigger": rows[0]["trigger"],
            "properties": [
                {"name": row["property_name"], "type": row["property_type"],
                 "description": row["property_description"],
                 "remark1": row["remark1"], "remark": row["remark"]}
                for row in rows if row["property_name"]
            ],
        })
    payload = {
        "contract_version": "gagasort-tracking-v1",
        "source_file": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "event_count": len(groups),
        "property_count": sum(len(x["properties"]) for x in groups),
        "events": groups,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_contract(path: Path) -> list[dict]:
    payload = json.loads(path.read_text())
    return [
        {
            "event_label": event.get("event_label", ""),
            "event_name": event["event_name"],
            "trigger": event.get("trigger", ""),
            "properties": event.get("properties", []),
        }
        for event in payload.get("events", [])
    ]


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


def resolve_constants(files: list[Path]) -> dict[str, str]:
    constants = {}
    pattern = re.compile(r"\b(?:const\s+string|static\s+readonly\s+string)\s+(\w+)\s*=\s*\"([^\"]+)\"")
    for path in files:
        for match in pattern.finditer(strip_comments(path.read_text(errors="replace"))):
            constants[match.group(1)] = match.group(2)
    return constants


def method_bodies(text: str) -> list[dict]:
    """Return rough C# method spans; enough to follow dictionary helpers without parsing C#."""
    spans = []
    signature = re.compile(
        r"(?:public|private|protected|internal|static|virtual|override|async|partial|sealed|\s)+"
        r"[\w<>,\[\].?]+\s+(\w+)\s*\([^;{}]*\)\s*\{"
    )
    for match in signature.finditer(text):
        depth = 1
        index = match.end()
        while index < len(text) and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        if depth == 0:
            spans.append({"name": match.group(1), "start": match.start(), "end": index,
                          "body": text[match.start():index]})
    return spans


def keys_from_body(body: str) -> set[str]:
    keys = set(re.findall(r"\{\s*[\"']([A-Za-z0-9_#]+)[\"']\s*,", body))
    # Most level events build a shared dictionary in a helper and append the
    # event-specific fields later via dic["field"] = value.
    keys.update(re.findall(r"\b\w+\s*\[\s*[\"']([A-Za-z0-9_#]+)[\"']\s*\]", body))
    return keys


def keys_for_call(text: str, call_offset: int, spans: list[dict]) -> list[str]:
    """Collect literal dictionary keys in the caller and its local helper methods."""
    owner = next((x for x in spans if x["start"] <= call_offset < x["end"]), None)
    if not owner:
        return sorted(keys_from_body(text[max(0, call_offset - 100):call_offset + 1000]))
    seen = set()
    pending = [owner]
    while pending:
        current = pending.pop()
        if current["name"] in seen:
            continue
        seen.add(current["name"])
        body = current["body"]
        keys = keys_from_body(body)
        for helper_name in re.findall(r"\b([A-Za-z_]\w*)\s*\(", body):
            if helper_name in {current["name"], "if", "for", "while", "switch", "return"}:
                continue
            helper = next((x for x in spans if x["name"] == helper_name), None)
            if helper and helper["name"] not in seen:
                pending.append(helper)
        seen.update({"__keys__"})
        if current is owner:
            result = keys
        else:
            result |= keys
    return sorted(result)


def scan_source(root: Path) -> dict[str, list[dict]]:
    files = sorted((root / "GagaSort/Assets/Scripts").rglob("*.cs"))
    constants = resolve_constants(files)
    return_reward_keys: set[str] = set()
    for source_path in files:
        source_text = strip_comments(source_path.read_text(errors="replace"))
        helper = next((x for x in method_bodies(source_text) if x["name"] == "ReportReturnReward"), None)
        if helper:
            return_reward_keys.update(keys_from_body(helper["body"]))
    direct = re.compile(r"CustomDataReport\s*\(\s*\"([^\"]+)\"")
    indirect = re.compile(r"CustomDataReport\s*\(\s*(\w+)\s*,")
    return_reward = re.compile(r"(?:\bDataReport\s*\.\s*)?ReportReturnReward\s*\(\s*\"([^\"]+)\"")
    events: dict[str, list[dict]] = {}
    for path in files:
        lines = path.read_text(errors="replace").splitlines()
        text = strip_comments("\n".join(lines))
        spans = method_bodies(text)
        occurrences: list[tuple[str, int, set[str]]] = []
        for match in direct.finditer(text):
            occurrences.append((match.group(1), match.start(), set()))
        for match in indirect.finditer(text):
            if match.group(1) in constants:
                occurrences.append((constants[match.group(1)], match.start(), set()))
        for match in return_reward.finditer(text):
            occurrences.append((match.group(1), match.start(), set(return_reward_keys)))
        for event, offset, override_keys in occurrences:
            line_no = text.count("\n", 0, offset) + 1
            keys = sorted(override_keys) if override_keys else keys_for_call(text, offset, spans)
            events.setdefault(event, []).append({
                "path": str(path.relative_to(root)), "line": line_no, "keys": keys,
            })
    return events


def category(label: str) -> str:
    if label in {"关卡点位", "道具资源点位", "体力日志", "货币日志", "新手引导", "激励广告", "激励广告点击", "插屏广告监控"}:
        return "玩法"
    if label in {"活动任务", "回流奖励", "分层快照", "按钮点击", "付费内容页面展示", "支付购买恢复", "广告请求失败", "评论引导", "登录监控"}:
        return "系统"
    return "埋点"


def slug(event: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", event).strip("-").lower()


def trace(path: str, line: int, note: str) -> dict:
    return {"path": path, "line": line, "end_line": line, "note": note}


def audit(root: Path, contract: list[dict]) -> dict:
    found = scan_source(root)
    table_events = {x["event_name"] for x in contract}
    code_only = sorted(set(found) - table_events)
    features = []
    findings = []
    common_entry = "GagaSort/Assets/Scripts/AWFramework/Platform/Interface.cs"
    common_line = 1068
    for event in contract:
        name = event["event_name"]
        calls = found.get(name, [])
        props = [p["name"] for p in event.get("properties", []) if p.get("name")]
        label = event.get("event_label") or "埋点事件"
        refs = [trace(c["path"], c["line"], f"{name} 上报调用与参数字典") for c in calls]
        source_paths = list(dict.fromkeys(c["path"] for c in calls))
        checks = []
        if name.startswith("ta_"):
            finding = "表中定义为 SDK 自动采集事件，代码侧没有同名 CustomDataReport 调用；本地只能核对没有手工重复上报。"
            verdict = "未见问题"
            if not refs:
                refs = [trace(common_entry, common_line, f"统一 CustomDataReport 出口；未发现 {name} 手工上报")]
                source_paths = [common_entry]
            if calls:
                finding = "SDK 自动采集事件又被业务代码手工上报，存在重复收数风险。"
                verdict = "发现问题"
        elif not calls:
            finding = "埋点表要求该事件，但当前 C# 代码没有找到同名或可解析常量的上报出口。"
            verdict = "发现问题"
            issue_id = f"TRACK-MISSING-{slug(name)}"
            findings.append({
                "id": issue_id, "kind": "静态缺陷已证", "title": f"{name} 没有找到代码上报出口",
                "status": "静态已证", "condition": f"触发{event.get('trigger') or '表定义的业务时机'}时",
                "cause": "埋点契约中的事件名没有在当前 C# 上报调用链出现。",
                "impact": f"后台无法收到 {name}，相关漏斗/功能数据缺失。",
                "expected": "在真实业务触发点通过统一埋点出口上报该事件。",
                "actual": "当前源码扫描未找到同名事件或可解析常量。",
                "missing": "需要确认是否由 SDK 自动采集、原生层或尚未接入。",
                "source_paths": [common_entry], "related": [], "display": {
                    "category": "埋点", "title": f"{name} 没有找到代码上报出口",
                    "condition": f"触发{event.get('trigger') or '表定义的业务时机'}时",
                    "cause": "契约事件名没有出现在当前 C# 上报链路。", "impact": f"{name} 可能漏报。",
                    "expected": "业务触发时能通过统一出口上报。", "actual": "当前源码未找到上报调用。",
                    "whitebox_steps": [f"在 GagaSort/Assets/Scripts 下搜索 CustomDataReport 和事件名 {name}。", "沿业务触发入口确认是否存在原生/SDK 自动采集替代。", "若无替代，补齐上报并核对参数。"],
                }, "static_proof": {"basis": "本地固化埋点表", "preconditions": event.get("trigger") or "契约触发时机", "entry": "C# CustomDataReport 调用扫描", "trace": [trace(common_entry, common_line, f"统一 CustomDataReport 出口；未发现 {name} 事件名调用")], "contradiction": "契约要求存在，当前代码无调用。", "steps": [f"搜索事件名 {name}。", "核对是否存在可解析常量。"]}
            })
            refs = [trace(common_entry, common_line, f"统一 CustomDataReport 出口；未发现 {name} 事件名调用")]
            source_paths = [common_entry]
        else:
            all_keys = sorted(set(k for c in calls for k in c["keys"]))
            missing = sorted(set(props) - set(all_keys))
            if missing and name not in {"activity_task", "user_tier"}:
                finding = f"找到 {len(calls)} 个上报出口，但没有在调用窗口中发现契约属性：{', '.join(missing)}。"
                verdict = "发现问题"
                issue_id = f"TRACK-PROP-{slug(name)}"
                findings.append({
                    "id": issue_id, "kind": "静态缺陷已证", "title": f"{name} 缺少契约属性",
                    "status": "静态已证", "condition": event.get("trigger") or "事件触发时",
                    "cause": "上报参数字典未覆盖埋点表要求的属性。", "impact": f"{name} 的 {', '.join(missing)} 无法用于分析。",
                    "expected": "每个适用分支传入契约要求的属性。", "actual": f"当前扫描到的属性为：{', '.join(all_keys) or '无'}。",
                    "missing": "需区分条件属性与确实漏传，并核对每个调用分支。", "source_paths": source_paths,
                    "display": {"category": "埋点", "title": f"{name} 缺少契约属性", "condition": event.get("trigger") or "事件触发时", "cause": "参数字典没有覆盖契约字段。", "impact": f"缺少 {', '.join(missing)}，数据分析可能失真。", "expected": "适用分支完整传入字段。", "actual": f"实际扫描到：{', '.join(all_keys) or '无'}。", "whitebox_steps": [f"定位 {name} 的每个 CustomDataReport 调用。", f"逐个核对 {', '.join(missing)} 是否在该分支真实赋值。", "确认条件字段是否由业务合同明确允许为空。"]},
                    "static_proof": {"basis": "本地固化埋点表", "preconditions": event.get("trigger") or "事件触发时", "entry": "; ".join(source_paths), "trace": refs, "contradiction": f"契约字段 {', '.join(missing)} 在所有扫描调用中均未发现。", "steps": [f"检查 {name} 的所有上报分支。", "对照契约属性列表核对缺失字段。"]}
                })
                refs = refs or []
            else:
                finding = f"找到 {len(calls)} 个上报出口；代码侧出现的字段为 {', '.join(all_keys) or '无'}。条件字段需按活动/结果分支继续核对。"
                verdict = "未见问题"
        issue_ids = [x["id"] for x in findings if slug(name) in x["id"].lower()]
        for dim, text in [
            ("入口与正常链路", f"核对 {name} 的触发说明与 CustomDataReport 上报出口。"),
            ("边界与异常", "核对缺失字段、空值、失败分支和 SDK 自动采集边界。"),
            ("重复与异步", "核对页面重入、回调重入和自动采集与手工上报重复。"),
            ("状态与持久化", "核对事件参数是否来自最终业务状态，而不是旧缓存或默认值。"),
            ("配置变化", "核对活动/礼包/关卡配置变化后事件名和字段仍由统一出口生成。"),
            ("升级与重装", "核对埋点去重、用户身份和本地状态在升级/重装链路中的影响。"),
            ("跨模块影响", "核对事件与玩法、系统、奖励、支付及后台分析字段的耦合。"),
        ]:
            case = {"id": f"tracking-{slug(name)}-{len(checks)+1:02d}", "dimension": dim, "scenario": f"{name}：{text}", "preconditions": event.get("trigger") or "当前代码进入该事件触发时机", "input": f"按 {name} 的业务触发顺序读取入口、门禁、参数构造和统一上报出口。", "basis": "本地固化埋点表与当前 C# 源码扫描。", "expected": "事件名、适用属性、触发时机和去重边界符合契约。", "actual": finding, "verdict": verdict, "trace": refs, "finding_ids": issue_ids, "run_ids": []}
            if verdict == "发现问题":
                case["reason"] = "已发现静态契约矛盾，详见关联问题。"
            checks.append(case)
        features.append({
            "id": f"TRACK-{slug(name)}", "name": name, "summary": f"{label}：{event.get('trigger') or '埋点事件'}", "status": "已完成" if verdict in {"未见问题", "发现问题"} else "未完成", "checks": checks, "gaps": [], "installation": {"upgrade": "埋点代码随包覆盖更新；本地事件去重和用户身份字段需保持兼容。", "same_identity": "清本地恢复同一身份时，不能因缓存重置重复上报一次性事件。", "new_identity": "新身份应按 SDK 口径重新开始采集，不能复用旧身份的本地去重标记。", "cause": "基于事件上报出口、SDK 身份和本地状态的静态影响分析。"}, "scope": "埋点契约静态审查", "source_paths": source_paths, "source_drift": [], "related_findings": issue_ids, "assessment": {"code_review": "完成静态审查", "code_conclusion": finding, "verdict": "发现静态缺陷" if verdict == "发现问题" else "局部检查未见问题", "conclusion": finding, "follow_up": "条件字段、真实 SDK 收数和服务端合同仍需外部验证。", "run_ids": []}, "display": {"category": "埋点", "group": label or "埋点事件", "name": name, "check_summary": f"{event.get('trigger') or '触发时机'}；事件名、属性、重复上报和参数来源"}, "static_audit": {"status": "已完成" if verdict in {"未见问题", "发现问题"} else "未完成", "summary": finding, "cases": checks}, "external_checks": [{"id": f"{slug(name)}-sdk", "assertion": "真实 SDK 是否最终收到并按表字段入库", "dependency": "真实平台/SDK行为", "why_not_local": "本地只能证明代码构造并调用统一出口，不能读取真实 SDK/服务端收数。", "local_case_ids": [x["id"] for x in checks], "remaining_fact": "设备或 SDK 日志中的实际入库结果。"}]})
    # 代码中有上报、但当前固化表没有定义的事件不能直接判为产品 Bug，
    # 单独列为棕色“契约待确认”，防止漏报和错报混在一起。
    for event in code_only:
        calls = found[event]
        refs = [trace(c["path"], c["line"], f"代码存在 {event} 上报调用；固化表未定义") for c in calls]
        checks = []
        dimensions = [
            ("入口与正常链路", "确认该事件的业务入口和触发时机。"),
            ("边界与异常", "确认失败、空值和异常分支是否也有明确埋点口径。"),
            ("重复与异步", "确认回调重入、页面重进和自动采集是否重复上报。"),
            ("状态与持久化", "确认事件字段来自最终业务状态。"),
            ("配置变化", "确认配置切换不会改变未定义的事件口径。"),
            ("升级与重装", "确认覆盖安装和删除重装不会造成重复或丢失。"),
            ("跨模块影响", "确认该事件与奖励、支付、活动和后台分析的关系。"),
        ]
        for index, (dim, text) in enumerate(dimensions, 1):
            checks.append({
                "id": f"tracking-{slug(event)}-{index:02d}", "dimension": dim,
                "scenario": f"{event}：{text}", "preconditions": "当前 HEAD；代码中存在该事件调用。",
                "input": f"沿 {event} 的真实调用方和参数构造继续核对。",
                "basis": "当前 C# 源码与本地固化埋点表双向扫描。",
                "expected": "事件应在固化契约中有定义，或明确登记为平台/历史兼容事件。",
                "actual": f"代码发现 {len(calls)} 个调用，但固化表没有 {event}。",
                "verdict": "待核实", "reason": "当前表没有该事件，不能判定是合法扩展、历史兼容还是错报。",
                "trace": refs, "finding_ids": [], "run_ids": [],
            })
        features.append({
            "id": f"TRACK-CODE-{slug(event)}", "name": event,
            "summary": "代码存在、固化埋点表未定义，等待契约确认。", "status": "未完成",
            "checks": checks, "gaps": ["固化埋点表没有该事件定义。"],
            "installation": {"upgrade": "需确认版本覆盖后该事件是否继续保留及去重。", "same_identity": "需确认同一身份恢复时是否沿用事件去重状态。", "new_identity": "需确认新身份是否应重新上报该事件。", "cause": "代码与固化契约存在双向差异，当前无法判断合法性。"},
            "scope": "埋点契约静态审查", "source_paths": list(dict.fromkeys(c["path"] for c in calls)), "source_drift": [],
            "related_findings": [], "assessment": {"code_review": "局部静态审查", "code_conclusion": f"发现代码事件 {event}，但固化表未定义。", "verdict": "风险待确认", "conclusion": f"发现代码事件 {event}，但固化表未定义。", "follow_up": "补充埋点表或确认该事件为合法平台/历史事件。", "run_ids": []},
            "display": {"category": "埋点", "group": "契约待确认", "name": event, "check_summary": "代码有上报，当前固化埋点表没有定义"},
            "static_audit": {"status": "未完成", "summary": f"代码发现 {event}，但固化表未定义，暂不判定为产品问题。", "cases": checks},
            "external_checks": []})
    extra = [{"event": e, "calls": calls} for e, calls in sorted(found.items()) if e not in table_events]
    return {"agent": "tracking-audit", "contract": {"event_count": len(contract), "property_count": sum(len(x.get("properties", [])) for x in contract)}, "features": features, "findings": findings, "code_only_events": extra, "scan_summary": {"table_events": len(table_events), "code_events": len(found), "matched_events": len(table_events & set(found)), "missing_events": len(table_events - set(found)), "code_only_events": len(code_only)}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--table", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--freeze-csv", type=Path)
    parser.add_argument("--freeze-json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.table:
        records = load_xlsx(args.table)
        save_contract(records, args.freeze_csv or args.root / "tracking-contract.csv", args.freeze_json or args.root / "tracking-contract.json", args.table)
        contract_path = args.freeze_json or args.root / "tracking-contract.json"
    elif args.contract:
        contract_path = args.contract
    else:
        raise SystemExit("必须提供 --table 或 --contract")
    dossier = audit(args.root, load_contract(contract_path))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dossier, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dossier["scan_summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
