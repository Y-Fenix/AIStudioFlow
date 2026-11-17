#!/usr/bin/env python3
"""Local Feishu authorization bridge for the GagaSort HTML report.

The report is deliberately static and must not contain an app secret or a
long-lived access token.  This small localhost service delegates user OAuth
and Base API calls to the installed ``lark-cli``.  It never returns the token
to the browser; the browser only receives authorization state, field names,
and the result of an explicit record-submit click.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from urllib.parse import parse_qs, urlparse
from typing import Any
from codex_modules import prepare_module_rows


MAX_BODY = 2 * 1024 * 1024
MAX_RECORDS = 200
ALLOWED_HOST_SUFFIXES = ("feishu.cn", "larksuite.com", "larkoffice.com")
BRIDGE_PROTOCOL = 2
REQUIRED_SCOPES = ("base:block:read", "base:field:read", "base:field:update", "base:view:read", "base:record:create")


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


def envelope(stdout: str, stderr: str = "") -> dict:
    """Parse lark-cli JSON while tolerating a notifier line around it."""
    text = stdout.strip()
    candidates = [text]
    for line in text.splitlines():
        if line.lstrip().startswith("{"):
            candidates.append(line.strip())
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError((stderr or stdout or "lark-cli 没有返回 JSON").strip()[-2000:])


def data_of(value: dict) -> dict:
    data = value.get("data", {})
    return data if isinstance(data, dict) else {}


def cli_error(value: dict) -> RuntimeError:
    error = value.get("error", {})
    message = error.get("message") if isinstance(error, dict) else None
    return RuntimeError(message or "飞书 CLI 请求失败")


def normalize_field(item: dict) -> dict:
    item = dict(item)
    item["name"] = item.get("name") or item.get("field_name") or ""
    item["id"] = item.get("id") or item.get("field_id") or ""
    raw_type = item.get("type")
    item["type"] = {1: "text", 2: "number", 3: "select", 4: "select", 5: "datetime", 7: "checkbox", 11: "user", 15: "url", 17: "attachment", 19: "lookup", 20: "formula", 1001: "created_time", 1002: "modified_time", 1005: "auto_number"}.get(item.get("type"), item.get("type", ""))
    item["multiple"] = bool(item.get("multiple") or raw_type == 4)
    item["options"] = item.get("options") or item.get("property", {}).get("options") or []
    return item


def coerce(field: dict, value):
    kind = field["type"]
    if kind in {"text", "url", "phone", "email", "date", "datetime"}:
        return str(value)
    if kind == "select":
        values = value if isinstance(value, list) else [value]
        if any(str(v) not in field["options"] for v in values):
            raise ValueError(field["name"] + "：内容不在目标表选项中，请调整目标表或数据后重读")
        return [str(v) for v in values] if field["multiple"] else str(value)
    if kind in {"number", "currency", "percent", "rating"}:
        import math
        try:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError()
            return int(number) if number.is_integer() else number
        except (TypeError, ValueError):
            raise ValueError(field["name"] + "：需要有效数字") from None
    if kind == "checkbox":
        if isinstance(value, bool):
            return value
        if str(value).lower() not in {"1", "true", "yes", "是", "0", "false", "no", "否"}:
            raise ValueError(field["name"] + "：需要布尔值")
        return str(value).lower() in {"1", "true", "yes", "是"}
    return None


class Bridge:
    def __init__(self, cli: str = "lark-cli"):
        self.cli = cli
        self.lock = threading.RLock()
        self.auth = {
            "status": "idle",
            "verification_url": "",
            "qr_data_url": "",
            "error": "",
        }

    def run(self, args: list[str], timeout: int = 120) -> dict:
        env = os.environ.copy()
        env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        process = subprocess.run(
            [self.cli, *args],
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        value = envelope(process.stdout if process.returncode == 0 else process.stderr, process.stdout)
        if process.returncode != 0 or value.get("ok") is False:
            raise cli_error(value)
        return value

    def start_auth(self) -> dict:
        with self.lock:
            if self.auth["status"] == "pending":
                return dict(self.auth)
            self.auth = {"status": "starting", "verification_url": "", "qr_data_url": "", "error": ""}
        try:
            existing = self.cli_auth_status()
            if existing["status"] == "authorized":
                with self.lock:
                    self.auth.update(status="authorized", error="")
                return dict(self.auth)
            result = self.run(["auth", "login", "--scope", " ".join(REQUIRED_SCOPES), "--no-wait", "--json"])
            data = data_of(result)
            verification_url = data.get("verification_url") or result.get("verification_url")
            device_code = data.get("device_code") or result.get("device_code")
            if not verification_url or not device_code:
                raise RuntimeError("飞书 CLI 未返回 verification_url/device_code")
            qr_data_url = self.qr_data_url(verification_url)
            with self.lock:
                self.auth.update(status="pending", verification_url=verification_url, qr_data_url=qr_data_url)
            threading.Thread(target=self.finish_auth, args=(device_code,), daemon=True).start()
        except Exception as exc:  # noqa: BLE001 - returned as a user-facing bridge error
            with self.lock:
                self.auth.update(status="error", error=str(exc))
        return dict(self.auth)

    def finish_auth(self, device_code: str) -> None:
        try:
            self.run(["auth", "login", "--device-code", device_code, "--json"], timeout=900)
            status = self.cli_auth_status()
            if status["status"] != "authorized":
                raise RuntimeError(status["error"] or "授权已完成，但飞书 Base 读写权限仍不可用")
            with self.lock:
                self.auth.update(status="authorized", error="")
        except Exception as exc:  # noqa: BLE001 - the browser needs the actual reason
            with self.lock:
                self.auth.update(status="error", error=str(exc))

    def cli_auth_status(self) -> dict:
        """Read CLI auth state without exposing the token or full scope list."""
        try:
            result = self.run(["auth", "status", "--json"])
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return {"status": "idle", "error": f"无法读取飞书授权状态：{exc}"}
        user = result.get("identities", {}).get("user", {})
        if not isinstance(user, dict):
            return {"status": "idle", "error": "飞书 CLI 没有用户授权会话"}
        scopes = set(str(user.get("scope", "")).split())
        missing = [scope for scope in REQUIRED_SCOPES if scope not in scopes]
        if user.get("tokenStatus") in {"valid", "needs_refresh"} and not missing:
            return {"status": "authorized", "error": ""}
        if user.get("tokenStatus") in {"valid", "needs_refresh"} and missing:
            return {"status": "read_only", "error": "当前飞书授权缺少提单所需权限：" + ", ".join(missing)}
        return {"status": "idle", "error": "飞书用户授权不存在或已过期"}

    def auth_status(self) -> dict:
        with self.lock:
            if self.auth["status"] in {"pending", "starting"}:
                return dict(self.auth)
        current = self.cli_auth_status()
        with self.lock:
            self.auth.update(status=current["status"], error=current.get("error", ""))
            return dict(self.auth)

    def qr_data_url(self, verification_url: str) -> str:
        with tempfile.TemporaryDirectory(prefix="gagasort-qa-qr-") as folder:
            output = Path(folder) / "auth.png"
            env = os.environ.copy()
            env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
            env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
            process = subprocess.run(
                [self.cli, "auth", "qrcode", verification_url, "--output", "auth.png", "--size", "256"],
                cwd=folder,
                text=True,
                capture_output=True,
                timeout=30,
                env=env,
            )
            if process.returncode != 0 or not output.is_file():
                raise RuntimeError((process.stderr or process.stdout or "二维码生成失败").strip()[-2000:])
            return "data:image/png;base64," + base64.b64encode(output.read_bytes()).decode("ascii")

    @staticmethod
    def validate_url(url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES) or not parsed.path.startswith(("/base/", "/wiki/")):
            raise ValueError("请粘贴飞书 HTTPS 多维表格或 Wiki 表格 URL")

    def fields(self, value: str) -> dict[str, Any]:
        self.validate_url(value)
        url = value
        payload = self.run(["base", "+url-resolve", "--url", url, "--as", "user", "--json"])
        data = payload.get("data") or {}
        base_token = data.get("base_token")
        table_id = data.get("table_id")
        query = parse_qs(urlparse(url).query)
        view_id = data.get("view_id") or (query.get("view") or [""])[0]
        if not base_token or not table_id:
            raise BridgeError("URL 未解析出可写入的 Base 数据表")
        raw_fields = []
        offset = 0
        while True:
            field_payload = self.run(["base", "+field-list", "--as", "user", "--base-token", base_token,
                                      "--table-id", table_id, "--limit", "200", "--offset", str(offset), "--json"])
            field_data = data_of(field_payload)
            page = field_data.get("fields") or field_data.get("items") or []
            if not isinstance(page, list):
                raise BridgeError("字段返回格式无法识别，已停止，不能截断表头")
            raw_fields.extend(page)
            offset += len(page)
            more = field_data.get("has_more") is True or int(field_data.get("total") or 0) > offset
            if not more and len(page) < 200:
                break
            if not page or offset >= 10000:
                raise BridgeError("字段结果未完整返回，已停止，不能截断表头")
        fields = []
        for item in raw_fields:
            item = normalize_field(item)
            if not item.get("name") or any(f["name"] == item["name"] for f in fields):
                raise BridgeError("字段名缺失或重复，已停止，不能丢列")
            fields.append({
                "id": item.get("id", ""),
                "name": item["name"],
                "type": item.get("type", ""),
                "writable": item.get("type") in WRITABLE_TYPES,
                "multiple": bool(item.get("multiple")),
                "options": [
                    (option.get("name", "") if isinstance(option, dict) else str(option))
                    for option in item.get("options", [])
                    if option
                ],
            })
        if not fields:
            raise BridgeError("没有读取到可用的飞书表头")
        if view_id:
            try:
                visible_payload = self.run([
                    "base", "+view-get-visible-fields", "--as", "user",
                    "--base-token", base_token, "--table-id", table_id, "--view-id", view_id, "--json",
                ])
            except RuntimeError as exc:
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
            by_id = {str(field["id"]): field for field in fields if field.get("id")}
            by_name = {field["name"]: field for field in fields}
            ordered = []
            for item in candidates:
                if isinstance(item, str):
                    field_id = field_name = item
                elif isinstance(item, dict):
                    field_id = item.get("field_id") or item.get("id") or item.get("fieldId") or ""
                    field_name = item.get("name") or item.get("field_name") or item.get("fieldName") or ""
                else:
                    raise BridgeError("视图字段格式无法识别")
                field = by_id.get(str(field_id)) or by_name.get(str(field_name))
                if not field:
                    raise BridgeError("视图字段无法与数据表匹配，已停止，不能丢列")
                if field not in ordered:
                    ordered.append(field)
            fields = ordered
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
            "fields": fields,
            "view_order_source": order_source,
        }

    def records(self, url: str, records: list[dict], headers: list[str] | None = None) -> dict:
        if not isinstance(records, list) or not records or len(records) > MAX_RECORDS:
            raise ValueError(f"提单记录必须为 1～{MAX_RECORDS} 条")
        structure = self.fields(url)
        if headers is not None and headers != structure["headers"]:
            raise ValueError("目标表头已变化，请重新读取后再提单")
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("提单记录格式错误")
        names = list(dict.fromkeys(name for record in records for name in record))
        values = [[record.get(name) for name in names] for record in records]
        structure, values = prepare_module_rows(structure, names, values, self.run)
        records = [dict(zip(names, row)) for row in values]
        structure["fields"] = structure["columns"]
        fields = {item["name"]: item for item in structure["fields"] if item["writable"]}
        payload = []
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("提单记录格式错误")
            mapped = {}
            for name, value in record.items():
                if name not in fields or value in ("", None):
                    continue
                converted = coerce(fields[name], value)
                if converted is not None:
                    mapped[name] = converted
            if not mapped:
                raise ValueError("存在没有可写入内容的记录，请检查表头映射")
            payload.append(mapped)
        try:
            result = self.run(["base", "+record-batch-create", "--as", "user", "--base-token", structure["base_token"],
                               "--table-id", structure["table_id"], "--json", json.dumps({"create_records": payload}, ensure_ascii=False)], timeout=180)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("提交未确认，可能已写入部分记录，请先核对目标表，勿重复提交：" + str(exc)) from exc
        created = data_of(result).get("record_id_list")
        if not isinstance(created, list) or len(created) != len(payload) or not all(isinstance(row, str) and row for row in created) or data_of(result).get("ignored_fields"):
            raise RuntimeError("提交响应未完整确认全部记录，请先核对目标表，勿重复提交")
        return {"submitted": len(created), "total": len(payload)}


class Handler(BaseHTTPRequestHandler):
    bridge: Bridge

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def send_json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_json(204, {})

    def do_GET(self) -> None:  # noqa: N802
        try:
            if self.path == "/health":
                self.send_json(200, {"ok": True, "service": "gagasort-feishu-bridge", "protocol": BRIDGE_PROTOCOL, "cli": shutil.which(self.bridge.cli) or self.bridge.cli})
            elif self.path == "/auth/status":
                self.send_json(200, {"ok": True, **self.bridge.auth_status()})
            else:
                self.send_json(404, {"ok": False, "error": "未知桥接地址"})
        except Exception as exc:  # noqa: BLE001
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY:
                raise ValueError("请求体过大")
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
            if self.path == "/auth/start":
                self.send_json(200, {"ok": True, **self.bridge.start_auth()})
            elif self.path == "/base/fields":
                self.send_json(200, {"ok": True, **self.bridge.fields(str(body.get("url", "")))})
            elif self.path == "/base/records":
                self.send_json(200, {"ok": True, **self.bridge.records(str(body.get("url", "")), body.get("records"), body.get("headers"))})
            else:
                self.send_json(404, {"ok": False, "error": "未知桥接地址"})
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})
        except subprocess.TimeoutExpired:
            self.send_json(504, {"ok": False, "error": "飞书 CLI 请求超时"})
        except Exception as exc:  # noqa: BLE001
            self.send_json(500, {"ok": False, "error": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17321)
    parser.add_argument("--cli", default="lark-cli")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("桥接只允许监听本机回环地址")
    bridge = Bridge(args.cli)
    Handler.bridge = bridge
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"GagaSort Feishu bridge listening at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
