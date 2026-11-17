"""Prepare explicit Codex module values before a user-triggered Bug import."""
from copy import deepcopy
import re
import json
import threading

MODULE_HEADERS = {"功能模块", "需求模块", "模块", "所属模块"}
_lock = threading.RLock()


def module_value(value):
    if not isinstance(value, str):
        raise ValueError("功能模块必须是非空名称")
    name = value.strip()
    if name.startswith("【Codex-") and name.endswith("】"):
        name = name[7:-1].strip()
    name = re.sub(r"^[\s✅☑✔✓\ufe0f]+", "", name).strip()
    if not name:
        raise ValueError("功能模块不能为空；未创建 Bug")
    return "【Codex-" + name + "】"


def prepare_module_rows(schema, headers, rows, run):
    """Read latest select definition, append missing options, then verify.

    Only import handlers call this function. Schema reads never mutate fields.
    The lock serializes this bridge's field updates; it cannot lock remote editors.
    """
    schema, rows = deepcopy(schema), deepcopy(rows)
    fields = {f["name"]: f for f in schema.get("columns", [])}
    if any(name in MODULE_HEADERS for name in fields) and not any(name in MODULE_HEADERS for name in headers):
        raise ValueError("提单数据缺少功能模块列；未创建 Bug")
    targets = [(index, name) for index, name in enumerate(headers) if name in MODULE_HEADERS]
    for index, name in targets:
        field = fields.get(name)
        if not field or not field.get("writable"):
            raise ValueError("功能模块字段不存在或不可写；未创建 Bug")
        if field.get("type") not in {"text", "select"}:
            raise ValueError("功能模块必须为文本或静态选项字段；未创建 Bug")
        required = []
        for row in rows:
            if index >= len(row):
                raise ValueError("功能模块不能为空；未创建 Bug")
            row[index] = module_value(row[index])
            if row[index] not in required:
                required.append(row[index])
        if field["type"] == "text" or not required:
            continue
        if not field.get("id"):
            raise ValueError("功能模块缺少字段 ID；未创建 Bug")
        args = ["--as", "user", "--base-token", schema["base_token"],
                "--table-id", schema["table_id"], "--field-id", field["id"]]

        def read_field():
            result = run(["base", "+field-get", *args, "--json"])
            current = (result.get("data") or {}).get("field")
            if not isinstance(current, dict) or current.get("name") != name or current.get("type") != "select":
                raise ValueError("功能模块字段结构变化，请重读表头；未创建 Bug")
            if current.get("dynamic_options_source") is not None:
                raise ValueError("功能模块是动态选项，不能覆盖为静态选项；未创建 Bug")
            options = current.get("options")
            if not isinstance(options, list) or any(not isinstance(o, dict) or not o.get("name") for o in options):
                raise ValueError("功能模块选项未完整读取；未创建 Bug")
            return current

        with _lock:
            current = read_field()
            options = current["options"]
            names = [o["name"] for o in options]
            missing = [value for value in required if value not in names]
            if missing:
                if len(options) + len(missing) > 10000:
                    raise ValueError("功能模块选项超过上限；未创建 Bug")
                body = {key: deepcopy(current[key]) for key in
                        ("name", "type", "multiple", "description", "default_value") if key in current}
                body["multiple"] = bool(current.get("multiple"))
                body["options"] = [{key: option[key] for key in ("name", "hue", "lightness") if key in option}
                                   for option in options] + [{"name": value} for value in missing]
                run(["base", "+field-update", *args, "--json", json.dumps(body, ensure_ascii=False), "--yes"])
                current = read_field()
                names_after = {o["name"] for o in current["options"]}
                if not set(names + required).issubset(names_after):
                    raise ValueError("功能模块创建未确认，请重读表头后重试；未创建 Bug")
                for key in ("multiple", "description", "default_value"):
                    if key in body and current.get(key, False if key == "multiple" else None) != body[key]:
                        raise ValueError("功能模块原配置保留未确认；未创建 Bug")
            field["options"] = [o["name"] for o in current["options"]]
            field["multiple"] = bool(current.get("multiple"))
    return schema, rows
