#!/usr/bin/env python3
"""Local Feishu Base bridge for the generated QA HTML report.

Credentials remain in the local lark-cli profile. The HTML report only sends
the pasted URL and mapped rows; it never receives a token or cookie.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse
from codex_modules import MODULE_HEADERS, prepare_module_rows


WRITABLE_TYPES = {
    "text", "select", "number", "currency", "percent", "rating", "checkbox",
    "date", "datetime", "url", "phone", "email",
}
MAX_RECORDS_PER_REQUEST = 200
VIEW_ORDER_KEYS = ("items", "fields", "visible_fields", "field_ids", "visible_field_ids")
ORDER_KEYS = (
    "display_order", "displayOrder", "order", "index", "sequence",
    "position", "sort_order", "sortOrder",
)


class BridgeError(RuntimeError):
    pass


class PartialImportError(BridgeError):
    def __init__(
        self,
        message: str,
        *,
        submitted: int,
        total: int,
        batches: int,
        batch_sizes: list[int],
    ) -> None:
        super().__init__(message)
        self.submitted = submitted
        self.total = total
        self.batches = batches
        self.batch_sizes = batch_sizes


def _json_error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def _run_lark(args: list[str]) -> dict[str, Any]:
    env = os.environ.copy()
    env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    try:
        completed = subprocess.run(
            ["lark-cli", *args],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BridgeError(f"lark-cli 执行失败：{exc}") from exc
    raw = (completed.stdout or completed.stderr).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError("lark-cli 返回了无法解析的结果") from exc
    if completed.returncode != 0 or payload.get("ok") is False:
        error = payload.get("error") or {}
        raise BridgeError(str(error.get("message") or "飞书接口调用失败"))
    return payload


def _validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BridgeError("目标 URL 必须是 http:// 或 https:// 地址")
    return value


def resolve_base_url(value: str) -> dict[str, Any]:
    url = _validate_url(value)
    payload = _run_lark(["base", "+url-resolve", "--url", url, "--as", "user", "--json"])
    data = payload.get("data") or {}
    base_token = data.get("base_token")
    table_id = data.get("table_id")
    query = parse_qs(urlparse(url).query)
    view_id = data.get("view_id") or (query.get("view") or [""])[0]
    if not base_token or not table_id:
        raise BridgeError("URL 未解析出可写入的 Base 数据表")
    raw_fields = (((data.get("hint") or {}).get("fields") or {}).get("fields") or [])
    fields = []
    for item in raw_fields:
        if not item.get("name"):
            continue
        fields.append({
            "id": item.get("id", ""),
            "name": item["name"],
            "type": item.get("type", ""),
            "writable": item.get("type") in WRITABLE_TYPES,
            "multiple": bool(item.get("multiple")),
            "options": [
                option.get("name", "")
                for option in item.get("options", [])
                if option.get("name")
            ],
        })
    if view_id:
        try:
            visible_payload = _run_lark([
                "base", "+view-get-visible-fields", "--as", "user",
                "--base-token", base_token, "--table-id", table_id, "--view-id", view_id, "--json",
            ])
        except BridgeError as exc:
            raise BridgeError(
                "无法读取目标视图的可见字段顺序："
                f"{exc}；请先执行 `lark-cli auth login --scope base:view:read` 授权后重试"
            ) from exc
        visible_data = visible_payload.get("data") or {}
        candidates = []
        order_source = ""
        for key in VIEW_ORDER_KEYS:
            values = visible_data.get(key)
            if isinstance(values, list):
                if values:
                    candidates = values
                    order_source = f"view-visible-fields:{key}"
                    break
        if not candidates:
            raise BridgeError(
                "目标视图未返回可见字段顺序；不能安全推断表头，请检查 view ID 和 `base:view:read` 权限"
            )
        if any(
            isinstance(item, dict) and any(key in item for key in ORDER_KEYS)
            for item in candidates
        ):
            def item_order(item: Any) -> tuple[int, int]:
                if not isinstance(item, dict):
                    return (1, 0)
                for key in ORDER_KEYS:
                    if key in item:
                        try:
                            return (0, int(item[key]))
                        except (TypeError, ValueError):
                            break
                return (1, 0)
            candidates = sorted(enumerate(candidates), key=lambda pair: (item_order(pair[1]), pair[0]))
            candidates = [item for _, item in candidates]
        visible_ids = []
        visible_names = []
        for item in candidates:
            if isinstance(item, str):
                field_id = item
                # The API may return either field IDs or field names as strings.
                # Keep both candidates and resolve by ID first, then by name.
                field_name = item
            elif isinstance(item, dict):
                field_id = item.get("field_id") or item.get("id") or item.get("fieldId") or ""
                field_name = item.get("name") or item.get("field_name") or item.get("fieldName") or ""
            else:
                field_id = ""
                field_name = ""
            if field_id and field_id not in visible_ids:
                visible_ids.append(str(field_id))
            if field_name and field_name not in visible_names:
                visible_names.append(str(field_name))
        by_id = {str(field.get("id")): field for field in fields if field.get("id")}
        ordered = [by_id[field_id] for field_id in visible_ids if field_id in by_id]
        if not ordered and visible_names:
            by_name = {str(field.get("name")): field for field in fields}
            ordered = [by_name[name] for name in visible_names if name in by_name]
        if ordered:
            fields = ordered
        else:
            raise BridgeError(
                "目标视图返回的字段无法与数据表字段匹配；不能安全推断表头顺序"
            )
    else:
        order_source = "table-fields"
    return {
        "url": url,
        "base_token": base_token,
        "table_id": table_id,
        "view_id": view_id or "",
        "title": data.get("title") or data.get("block_name") or "",
        "headers": [field["name"] for field in fields],
        "columns": fields,
        "view_order_source": order_source,
    }


def _coerce(field: dict[str, Any], value: Any) -> Any:
    if value is None or value == "":
        return None
    kind = field.get("type")
    if kind in {"text", "url", "phone", "email"}:
        return str(value)
    if kind == "select":
        options = set(field.get("options") or [])
        if field.get("multiple"):
            values = value if isinstance(value, list) else [value]
            valid = [str(item) for item in values if str(item) in options]
            return valid or None
        return str(value) if str(value) in options else None
    if kind in {"number", "currency", "percent", "rating"}:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number
    if kind == "checkbox":
        return value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes", "是"}
    return str(value)


def records_from_rows(
    schema: dict[str, Any],
    headers: list[str],
    rows: list[list[Any]],
) -> list[dict[str, Any]]:
    fields = {field["name"]: field for field in schema.get("columns", [])}
    records: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {}
        for index, header in enumerate(headers):
            field = fields.get(header)
            if header in MODULE_HEADERS and (not field or not field.get("writable")):
                raise BridgeError("功能模块字段不存在或不可写；未创建 Bug")
            if not field or not field.get("writable"):
                continue
            value = _coerce(field, row[index] if index < len(row) else None)
            if header in MODULE_HEADERS and value is None:
                raise BridgeError("功能模块未配置或不在目标表选项中；未创建 Bug")
            if value is not None:
                record[header] = value
        if not record:
            raise BridgeError("没有可写入的字段；请检查 Bug 表头映射")
        records.append(record)
    if not records:
        raise BridgeError("没有可导入的用例")
    return records


def import_rows(url: str, headers: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    if not rows or not all(isinstance(header, str) for header in headers):
        raise BridgeError("没有可导入的用例或表头格式无效")
    schema = resolve_base_url(url)
    schema, rows = prepare_module_rows(schema, headers, rows, _run_lark)
    return create_records_batched(schema, records_from_rows(schema, headers, rows))


def create_records(schema: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise BridgeError("没有可导入的用例")
    if len(records) > MAX_RECORDS_PER_REQUEST:
        raise BridgeError(f"单批最多提交 {MAX_RECORDS_PER_REQUEST} 条用例")
    payload = _run_lark([
        "base", "+record-batch-create", "--as", "user",
        "--base-token", schema["base_token"], "--table-id", schema["table_id"],
        "--json", json.dumps({"create_records": records}, ensure_ascii=False, separators=(",", ":")),
    ])
    return {"ok": True, "created": len(records), "result": payload.get("data") or {}}


def create_records_batched(schema: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise BridgeError("没有可导入的用例")
    chunks = [
        records[index:index + MAX_RECORDS_PER_REQUEST]
        for index in range(0, len(records), MAX_RECORDS_PER_REQUEST)
    ]
    submitted = 0
    results = []
    batch_sizes: list[int] = []
    for index, chunk in enumerate(chunks, start=1):
        try:
            result = create_records(schema, chunk)
        except BridgeError as exc:
            raise PartialImportError(
                f"第 {index} 批提交失败：已提交 {submitted}/{len(records)} 条，剩余记录未提交；{exc}",
                submitted=submitted,
                total=len(records),
                batches=len(chunks),
                batch_sizes=batch_sizes,
            ) from exc
        submitted += len(chunk)
        batch_sizes.append(len(chunk))
        results.append(result.get("result") or {})
    return {
        "ok": True,
        "created": submitted,
        "submitted": submitted,
        "total": len(records),
        "batches": len(chunks),
        "batch_sizes": batch_sizes,
        "result": results,
    }


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "QAFeishuBridge/1.0"

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"ok": True, "service": "qa-feishu-bridge"})
            return
        if parsed.path != "/schema":
            self._send(404, _json_error("未知接口"))
            return
        try:
            values = parse_qs(parsed.query).get("url") or []
            if not values:
                raise BridgeError("缺少 url 参数")
            schema = resolve_base_url(values[0])
            public = {key: schema[key] for key in ("title", "headers", "columns", "view_order_source")}
            self._send(200, {"ok": True, **public})
        except BridgeError as exc:
            self._send(400, _json_error(str(exc)))

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/import":
            self._send(404, _json_error("未知接口"))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            url = _validate_url(str(body.get("url") or ""))
            headers = body.get("headers") or []
            rows = body.get("rows") or ([body.get("row")] if body.get("row") is not None else [])
            if (
                not isinstance(headers, list)
                or not isinstance(rows, list)
                or not all(isinstance(row, list) for row in rows)
            ):
                raise BridgeError("导入数据格式无效")
            self._send(200, import_rows(url, headers, rows))
        except PartialImportError as exc:
            self._send(502, {
                "ok": False,
                "error": str(exc),
                "submitted": exc.submitted,
                "total": exc.total,
                "batches": exc.batches,
                "batch_sizes": exc.batch_sizes,
            })
        except (BridgeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send(400, _json_error(str(exc)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("桥接服务只允许绑定本机回环地址")
    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    print(f"QA Feishu bridge listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
