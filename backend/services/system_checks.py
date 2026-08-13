from __future__ import annotations

from typing import Any


SYSTEM_CHECK_TASK_TYPE = "system_device_check"
SYSTEM_CHECK_INDEX_START = 1000


def _default_field_key(title: str) -> str:
    return f"system_check:{title.casefold().strip()}"


def normalize_system_checks(content: Any) -> list[dict[str, Any]]:
    """Normalize frozen rule-pack system/device checks into visit-task specs."""
    if not isinstance(content, dict):
        return []

    raw_items = content.get("system_checks", [])
    if raw_items is None or raw_items == "":
        return []
    if not isinstance(raw_items, list):
        raise ValueError("规则包 system_checks 必须是数组")

    seen_titles: set[str] = set()
    seen_field_keys: set[str] = set()
    specs: list[dict[str, Any]] = []
    for position, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise ValueError(f"system_checks 第 {position} 项必须是对象")
        title = str(raw_item.get("title") or "").strip()
        if not title:
            raise ValueError(f"system_checks 第 {position} 项缺少 title")
        if len(title) > 200:
            raise ValueError(f"system_checks 第 {position} 项 title 不得超过 200 个字符")
        title_key = title.casefold()
        if title_key in seen_titles:
            raise ValueError(f"system_checks 存在重复任务名称：{title}")
        seen_titles.add(title_key)

        field_key = str(raw_item.get("key") or "").strip() or _default_field_key(title)
        if len(field_key) > 240:
            raise ValueError(f"system_checks 第 {position} 项 key 不得超过 240 个字符")
        if field_key in seen_field_keys:
            raise ValueError(f"system_checks 存在重复稳定任务键：{field_key}")
        seen_field_keys.add(field_key)

        required = raw_item.get("required", False)
        if not isinstance(required, bool):
            raise ValueError(f"system_checks 第 {position} 项 required 必须为 true 或 false")
        description = str(raw_item.get("description") or "").strip()
        if len(description) > 1000:
            raise ValueError(f"system_checks 第 {position} 项 description 不得超过 1000 个字符")

        specs.append(
            {
                "task_type": SYSTEM_CHECK_TASK_TYPE,
                "table_index": SYSTEM_CHECK_INDEX_START + position,
                "field_key": field_key,
                "title": title,
                "requires_evidence": required,
                "description": description,
            }
        )
    return specs
