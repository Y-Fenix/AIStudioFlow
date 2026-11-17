#!/usr/bin/env python3
import json
import unittest
from unittest.mock import patch

import feishu_bridge as bridge
from codex_modules import module_value, prepare_module_rows


class CodexModuleTests(unittest.TestCase):
    def test_module_format_is_idempotent_and_rejects_empty_names(self):
        for value in ["✅三阶段竞速比赛", "三阶段竞速比赛", "【Codex-三阶段竞速比赛】", "【Codex-✅三阶段竞速比赛】"]:
            self.assertEqual(module_value(value), "【Codex-三阶段竞速比赛】")
        for value in [None, [], "", "✅", "【Codex-】"]:
            with self.assertRaises(ValueError):
                module_value(value)

    def test_missing_module_column_and_blank_value_stop_before_field_write(self):
        for headers, rows in [(["缺陷描述"], [["缺陷"]]), (["功能模块"], [[""]])]:
            with patch.object(bridge, "_run_lark") as run:
                with self.assertRaises(ValueError):
                    prepare_module_rows(self.schema(), headers, rows, run)
                run.assert_not_called()

    def test_text_module_needs_no_field_mutation(self):
        schema = self.schema()
        schema["columns"][1]["type"] = "text"
        with patch.object(bridge, "_run_lark") as run:
            _, rows = prepare_module_rows(schema, ["功能模块"], [["✅删除账号功能"]], run)
            run.assert_not_called()
        self.assertEqual(rows, [["【Codex-删除账号功能】"]])

    def test_multiple_module_option_names_stay_explicit(self):
        field = self.field()
        field["multiple"] = True
        _, _, _, records = self.run_import(field)
        self.assertEqual(records[0]["功能模块"], ["【Codex-三阶段竞速比赛】"])

    def schema(self):
        return {"base_token": "fixture", "table_id": "tbl_fixture", "columns": [
            {"name": "缺陷描述", "type": "text", "writable": True},
            {"id": "fld_module", "name": "功能模块", "type": "select", "multiple": False,
             "writable": True, "options": ["【基础规则】"]},
        ]}

    def field(self):
        return {"id": "fld_module", "name": "功能模块", "type": "select", "multiple": False,
                "description": "原字段说明", "default_value": ["【基础规则】"],
                "options": [{"name": "【基础规则】", "hue": "Blue", "lightness": "Lighter"}]}

    def run_import(self, field=None, error=None, verify_missing=False):
        field = field or self.field()
        calls = []
        updates = []
        def run(args):
            calls.append(args)
            if "+field-get" in args:
                return {"ok": True, "data": {"field": field}}
            if "+field-update" in args:
                if error:
                    raise bridge.BridgeError(error)
                body = json.loads(args[args.index("--json") + 1])
                updates.append(body)
                if not verify_missing:
                    field.update(body)
                return {"ok": True, "data": {"updated": True}}
            raise AssertionError(args)
        rows = [["真实缺陷", "✅三阶段竞速比赛"], ["另一缺陷", "三阶段竞速比赛"]]
        with patch.object(bridge, "resolve_base_url", return_value=self.schema()), \
             patch.object(bridge, "_run_lark", side_effect=run), \
             patch.object(bridge, "create_records_batched", return_value={"ok": True}) as create:
            try:
                result = bridge.import_rows("https://example.feishu.cn/base/fixture", ["缺陷描述", "功能模块"], rows)
            except Exception:
                create.assert_not_called()
                raise
        return result, calls, updates, create.call_args.args[1]

    def test_creates_module_before_records_and_preserves_existing_field(self):
        _, calls, updates, records = self.run_import()
        self.assertEqual(len(updates), 1)
        self.assertIn("--yes", next(args for args in calls if "+field-update" in args))
        expected = {key: value for key, value in self.field().items() if key != "id"}
        expected["options"].append({"name": "【Codex-三阶段竞速比赛】"})
        self.assertEqual(updates[0], expected)
        self.assertEqual([record["功能模块"] for record in records], ["【Codex-三阶段竞速比赛】"] * 2)
        self.assertEqual(sum("+field-get" in args for args in calls), 2)

    def test_existing_codex_option_is_reused_without_updating_field(self):
        field = self.field()
        field["options"].append({"name": "【Codex-三阶段竞速比赛】"})
        _, _, updates, records = self.run_import(field)
        self.assertEqual(updates, [])
        self.assertEqual(records[0]["功能模块"], "【Codex-三阶段竞速比赛】")

    def test_permission_failure_prevents_record_creation(self):
        with self.assertRaisesRegex(bridge.BridgeError, "权限不足"):
            self.run_import(error="权限不足")

    def test_unconfirmed_option_creation_prevents_record_creation(self):
        with self.assertRaisesRegex(ValueError, "未确认"):
            self.run_import(verify_missing=True)

    def test_dynamic_options_are_not_replaced(self):
        field = self.field()
        field["dynamic_options_source"] = {"table_id": "source", "field_id": "field"}
        with self.assertRaisesRegex(ValueError, "动态"):
            self.run_import(field)

    def test_missing_module_option_cannot_be_silently_dropped(self):
        with self.assertRaisesRegex(bridge.BridgeError, "功能模块"):
            bridge.records_from_rows(self.schema(), ["缺陷描述", "功能模块"], [["缺陷", "✅三阶段竞速比赛"]])


class FeishuBridgeTests(unittest.TestCase):
    def setUp(self):
        self.schema = {
            "columns": [
                {"name": "缺陷描述", "type": "text", "writable": True},
                {
                    "name": "缺陷状态",
                    "type": "select",
                    "writable": True,
                    "options": ["未解决", "已拒绝"],
                },
                {"name": "创建人", "type": "created_by", "writable": False, "options": []},
            ],
        }

    def test_records_skip_system_fields_and_keep_valid_select(self):
        records = bridge.records_from_rows(
            self.schema,
            ["缺陷描述", "缺陷状态", "创建人"],
            [["步骤和异常", "未解决", "不应写入"]],
        )
        self.assertEqual(records, [{"缺陷描述": "步骤和异常", "缺陷状态": "未解决"}])

    def test_invalid_select_does_not_create_a_fake_record(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.records_from_rows(self.schema, ["缺陷状态"], [["不存在的选项"]])

    def test_resolve_url_uses_cli_and_returns_public_schema(self):
        payload = {
            "ok": True,
            "data": {
                "base_token": "secret",
                "table_id": "tblA",
                "title": "BUG",
                "hint": {
                    "fields": {
                        "fields": [{"name": "缺陷描述", "type": "text"}],
                    },
                },
            },
        }
        with patch.object(bridge, "_run_lark", return_value=payload) as mocked:
            result = bridge.resolve_base_url(
                "https://example.feishu.cn/wiki/token?table=tblA"
            )
        self.assertEqual(result["headers"], ["缺陷描述"])
        self.assertEqual(result["table_id"], "tblA")
        mocked.assert_called_once()

    def test_batch_create_sends_records_only_after_explicit_call(self):
        with patch.object(
            bridge,
            "_run_lark",
            return_value={"ok": True, "data": {"records": []}},
        ) as mocked:
            result = bridge.create_records(
                {"base_token": "secret", "table_id": "tblA"},
                [{"缺陷描述": "x"}],
            )
        self.assertEqual(result["created"], 1)
        args = mocked.call_args.args[0]
        self.assertIn("+record-batch-create", args)
        self.assertIn(
            json.dumps(
                {"create_records": [{"缺陷描述": "x"}]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            args,
        )

    def test_resolve_base_url_uses_view_field_order(self):
        resolve_payload = {
            "ok": True,
            "data": {
                "base_token": "secret",
                "table_id": "tblA",
                "hint": {"fields": {"fields": [
                    {"id": "fld_a", "name": "第二列", "type": "text"},
                    {"id": "fld_b", "name": "第一列", "type": "text"},
                ]}},
            },
        }
        visible_payload = {"ok": True, "data": {"items": [{"field_id": "fld_b"}, {"field_id": "fld_a"}]}}

        def run(args):
            return visible_payload if "+view-get-visible-fields" in args else resolve_payload

        with patch.object(bridge, "_run_lark", side_effect=run) as mocked:
            result = bridge.resolve_base_url(
                "https://example.feishu.cn/wiki/token?table=tblA&view=vewA"
            )
        self.assertEqual(result["headers"], ["第一列", "第二列"])
        self.assertEqual(result["view_id"], "vewA")
        self.assertEqual(result["view_order_source"], "view-visible-fields:items")
        self.assertEqual(mocked.call_count, 2)

    def test_resolve_base_url_does_not_append_hidden_fields(self):
        resolve_payload = {
            "ok": True,
            "data": {
                "base_token": "secret",
                "table_id": "tblA",
                "hint": {"fields": {"fields": [
                    {"id": "fld_visible", "name": "显示列", "type": "text"},
                    {"id": "fld_hidden", "name": "隐藏列", "type": "text"},
                ]}},
            },
        }
        visible_payload = {"ok": True, "data": {"items": [{"field_id": "fld_visible"}]}}

        def run(args):
            return visible_payload if "+view-get-visible-fields" in args else resolve_payload

        with patch.object(bridge, "_run_lark", side_effect=run):
            result = bridge.resolve_base_url(
                "https://example.feishu.cn/wiki/token?table=tblA&view=vewA"
            )
        self.assertEqual(result["headers"], ["显示列"])

    def test_resolve_base_url_matches_visible_field_names(self):
        resolve_payload = {
            "ok": True,
            "data": {
                "base_token": "secret",
                "table_id": "tblA",
                "hint": {"fields": {"fields": [
                    {"id": "fld_a", "name": "第二列", "type": "text"},
                    {"id": "fld_b", "name": "第一列", "type": "text"},
                ]}},
            },
        }
        visible_payload = {
            "ok": True,
            "data": {"visible_fields": ["第一列", "第二列"]},
        }

        def run(args):
            return visible_payload if "+view-get-visible-fields" in args else resolve_payload

        with patch.object(bridge, "_run_lark", side_effect=run):
            result = bridge.resolve_base_url(
                "https://example.feishu.cn/wiki/token?table=tblA&view=vewA"
            )
        self.assertEqual(result["headers"], ["第一列", "第二列"])

    def test_resolve_base_url_honors_explicit_view_order(self):
        resolve_payload = {
            "ok": True,
            "data": {
                "base_token": "secret",
                "table_id": "tblA",
                "hint": {"fields": {"fields": [
                    {"id": "fld_a", "name": "A", "type": "text"},
                    {"id": "fld_b", "name": "B", "type": "text"},
                ]}},
            },
        }
        visible_payload = {"ok": True, "data": {"items": [
            {"field_id": "fld_a", "display_order": 2},
            {"field_id": "fld_b", "display_order": 1},
        ]}}

        def run(args):
            return visible_payload if "+view-get-visible-fields" in args else resolve_payload

        with patch.object(bridge, "_run_lark", side_effect=run):
            result = bridge.resolve_base_url(
                "https://example.feishu.cn/wiki/token?table=tblA&view=vewA"
            )
        self.assertEqual(result["headers"], ["B", "A"])

    def test_batched_create_splits_319_records_into_200_and_119(self):
        records = [{"缺陷描述": str(index)} for index in range(319)]
        with patch.object(bridge, "create_records", side_effect=lambda schema, chunk: {
            "ok": True, "created": len(chunk), "result": {"count": len(chunk)},
        }) as mocked:
            result = bridge.create_records_batched(self.schema, records)
        self.assertEqual(result["submitted"], 319)
        self.assertEqual(result["total"], 319)
        self.assertEqual(result["batches"], 2)
        self.assertEqual(result["batch_sizes"], [200, 119])
        self.assertEqual([len(call.args[1]) for call in mocked.call_args_list], [200, 119])

    def test_batched_create_reports_partial_submission(self):
        records = [{"缺陷描述": str(index)} for index in range(319)]

        def create(_schema, chunk):
            if len(chunk) == 119:
                raise bridge.BridgeError("HTTP 400：超过单批上限")
            return {"ok": True, "created": len(chunk), "result": {}}

        with patch.object(bridge, "create_records", side_effect=create):
            with self.assertRaises(bridge.PartialImportError) as context:
                bridge.create_records_batched(self.schema, records)
        error = context.exception
        self.assertEqual(error.submitted, 200)
        self.assertEqual(error.total, 319)
        self.assertEqual(error.batches, 2)
        self.assertEqual(error.batch_sizes, [200])
        self.assertIn("已提交 200/319 条", str(error))


if __name__ == "__main__":
    unittest.main()
