from __future__ import annotations

import re
from typing import Any


TABLE_CELL_LOCATOR_PATTERN = re.compile(r"^T([1-9]\d*):R([1-9]\d*):C([1-9]\d*)$")
BODY_PARAGRAPH_LOCATOR_PATTERN = re.compile(r"^P([1-9]\d*)$")
HEADER_PARAGRAPH_LOCATOR_PATTERN = re.compile(r"^H([1-9]\d*):P([1-9]\d*)$")
FOOTER_PARAGRAPH_LOCATOR_PATTERN = re.compile(r"^F([1-9]\d*):P([1-9]\d*)$")
INLINE_TOKEN_LOCATOR_PATTERN = re.compile(
    r"^(?:(?P<region>[HF])(?P<section>[1-9]\d*):)?P(?P<paragraph>[1-9]\d*):(?P<token>\{\{[^{}\r\n]+\}\})$"
)
INLINE_TOKEN_PATTERN = re.compile(r"\{\{[^{}\r\n]+\}\}")
CONTENT_CONTROL_TAG_LOCATOR_PATTERN = re.compile(r"^SDT:(?P<identifier>[^\r\n]+)$")
CONTENT_CONTROL_ALIAS_LOCATOR_PATTERN = re.compile(r"^SDT_ALIAS:(?P<identifier>[^\r\n]+)$")
BOOKMARK_LOCATOR_PATTERN = re.compile(r"^BM:(?P<bookmark_name>[^\r\n]+)$")
MERGE_FIELD_LOCATOR_PATTERN = re.compile(r"^FIELD:(?P<field_name>[^\r\n]+)$")

SUPPORTED_TARGET_KINDS = {
    "table_cell",
    "body_paragraph",
    "header_paragraph",
    "footer_paragraph",
    "inline_token",
    "content_control",
    "bookmark",
    "merge_field",
}

SUPPORTED_VALUE_SOURCES = {
    "confirmed_text",
    "summary",
    "project.study_name",
    "project.study_id",
    "project.sponsor",
    "project.approval_number",
    "project.sop_version",
    "site.site_name",
    "site.pi_name",
    "site.protocol_version",
    "site.icf_version",
    "site.ethics_date",
    "visit.activity_period",
    "visit.visit_method",
    "visit.report_date",
    "visit.site_team",
    "visit.monitoring_team",
    "visit.next_visit",
}


def normalize_target_kind(value: str | None) -> str:
    target_kind = str(value or "table_cell").strip() or "table_cell"
    if target_kind not in SUPPORTED_TARGET_KINDS:
        raise ValueError("报告填写目标类型未被当前模板引擎支持")
    return target_kind


def find_inline_tokens(value: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in INLINE_TOKEN_PATTERN.finditer(str(value or ""))))


def parse_target_locator(value: str) -> tuple[int, int, int]:
    parsed = parse_slot_target("table_cell", value)
    return int(parsed["table_index"]), int(parsed["row_index"]), int(parsed["column_index"])


def parse_slot_target(target_kind: str | None, target_locator: str) -> dict[str, Any]:
    kind = normalize_target_kind(target_kind)
    locator = str(target_locator or "").strip()

    if kind == "table_cell":
        matched = TABLE_CELL_LOCATOR_PATTERN.fullmatch(locator)
        if matched is None:
            raise ValueError("表格填写位置应采用 T1:R1:C1 格式")
        table_index, row_index, column_index = (int(part) for part in matched.groups())
        return {
            "target_kind": kind,
            "table_index": table_index,
            "row_index": row_index,
            "column_index": column_index,
        }

    if kind == "body_paragraph":
        matched = BODY_PARAGRAPH_LOCATOR_PATTERN.fullmatch(locator)
        if matched is None:
            raise ValueError("正文段落填写位置应采用 P1 格式")
        return {"target_kind": kind, "paragraph_index": int(matched.group(1))}

    if kind == "header_paragraph":
        matched = HEADER_PARAGRAPH_LOCATOR_PATTERN.fullmatch(locator)
        if matched is None:
            raise ValueError("页眉段落填写位置应采用 H1:P1 格式")
        return {
            "target_kind": kind,
            "section_index": int(matched.group(1)),
            "paragraph_index": int(matched.group(2)),
        }

    if kind == "footer_paragraph":
        matched = FOOTER_PARAGRAPH_LOCATOR_PATTERN.fullmatch(locator)
        if matched is None:
            raise ValueError("页脚段落填写位置应采用 F1:P1 格式")
        return {
            "target_kind": kind,
            "section_index": int(matched.group(1)),
            "paragraph_index": int(matched.group(2)),
        }

    if kind == "content_control":
        matched = CONTENT_CONTROL_TAG_LOCATOR_PATTERN.fullmatch(locator)
        identity_kind = "tag"
        if matched is None:
            matched = CONTENT_CONTROL_ALIAS_LOCATOR_PATTERN.fullmatch(locator)
            identity_kind = "alias"
        if matched is None:
            raise ValueError("内容控件填写位置应采用 SDT:<标记> 或 SDT_ALIAS:<别名> 格式")
        return {
            "target_kind": kind,
            "identity_kind": identity_kind,
            "identifier": matched.group("identifier").strip(),
        }

    if kind == "bookmark":
        matched = BOOKMARK_LOCATOR_PATTERN.fullmatch(locator)
        if matched is None:
            raise ValueError("书签填写位置应采用 BM:<书签名称> 格式")
        return {
            "target_kind": kind,
            "bookmark_name": matched.group("bookmark_name").strip(),
        }

    if kind == "merge_field":
        matched = MERGE_FIELD_LOCATOR_PATTERN.fullmatch(locator)
        if matched is None:
            raise ValueError("Word 合并字段填写位置应采用 FIELD:<字段名称> 格式")
        return {
            "target_kind": kind,
            "field_name": matched.group("field_name").strip(),
        }

    matched = INLINE_TOKEN_LOCATOR_PATTERN.fullmatch(locator)
    if matched is None:
        raise ValueError("内联标记填写位置应采用 P1:{{字段}}、H1:P1:{{字段}} 或 F1:P1:{{字段}} 格式")
    region = matched.group("region")
    return {
        "target_kind": kind,
        "region": {None: "body", "H": "header", "F": "footer"}[region],
        "section_index": int(matched.group("section")) if matched.group("section") else None,
        "paragraph_index": int(matched.group("paragraph")),
        "token": matched.group("token"),
    }


def validate_slot_source(value_source: str, field_key: str) -> None:
    source = str(value_source or "").strip()
    if source not in SUPPORTED_VALUE_SOURCES:
        raise ValueError("报告填写来源未被当前模板引擎支持")
    if source == "confirmed_text" and not str(field_key or "").strip():
        raise ValueError("已确认文本来源必须指定关联任务字段键")
