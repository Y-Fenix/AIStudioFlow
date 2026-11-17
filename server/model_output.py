"""Parse only completed model text; never guess or rewrite business values."""
import json
import math
import re


class ModelOutputError(ValueError):
    def __init__(self, raw_text, message):
        super().__init__(message)
        # Private recovery data. Deliberately excluded from str/repr and telemetry.
        self.raw_text = raw_text


def parse_object(raw):
    text = raw.strip().lstrip('\ufeff').strip()
    fence = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```', text, re.IGNORECASE)
    if fence:
        text = fence.group(1)

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('non-finite number')
        return result

    def constant(_):
        raise ValueError('non-finite constant')

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)
    except (ValueError, RecursionError):
        raise ModelOutputError(raw, '模型返回内容不是合法JSON（必须为单个完整对象，不能有重复字段或非有限数值）') from None
    if not isinstance(value, dict):
        raise ModelOutputError(raw, '模型必须返回JSON对象')
    return value
