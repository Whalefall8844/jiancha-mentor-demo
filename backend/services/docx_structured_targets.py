from __future__ import annotations

import os
import re
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
MERGE_FIELD_INSTRUCTION_PATTERN = re.compile(
    r'^\s*MERGEFIELD\s+(?:"(?P<quoted>[^"]+)"|(?P<bare>[^\s\\]+))',
    re.IGNORECASE,
)


def _qn(local_name: str) -> str:
    return f"{{{W_NS}}}{local_name}"


def _word_part_names(names: Iterable[str]) -> list[str]:
    return [
        name
        for name in names
        if name == "word/document.xml"
        or (name.startswith("word/header") and name.endswith(".xml"))
        or (name.startswith("word/footer") and name.endswith(".xml"))
    ]


def _part_label(part_name: str) -> str:
    if part_name == "word/document.xml":
        return "正文"
    if part_name.startswith("word/header"):
        return f"页眉 {Path(part_name).stem.removeprefix('header')}"
    return f"页脚 {Path(part_name).stem.removeprefix('footer')}"


def _text_of(element: etree._Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.xpath(".//w:t/text()", namespaces=NS))


def _short_preview(value: str, fallback: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return fallback
    return text if len(text) <= 160 else text[:159] + "…"


def _sdt_value(sdt: etree._Element, property_name: str) -> str:
    return str(
        sdt.xpath(
            f"string(./w:sdtPr/w:{property_name}/@w:val)",
            namespaces=NS,
        )
        or ""
    ).strip()


def _range_text(root: etree._Element, start: etree._Element, end: etree._Element) -> str:
    nodes = list(root.iter())
    positions = {id(node): index for index, node in enumerate(nodes)}
    start_position = positions.get(id(start), -1)
    end_position = positions.get(id(end), -1)
    if start_position < 0 or end_position <= start_position:
        return ""
    return "".join(
        str(node.text or "")
        for node in nodes[start_position + 1 : end_position]
        if node.tag == _qn("t")
    )


def _merge_field_name(instruction: str) -> str:
    matched = MERGE_FIELD_INSTRUCTION_PATTERN.match(str(instruction or ""))
    if matched is None:
        return ""
    return str(matched.group("quoted") or matched.group("bare") or "").strip()


def _simple_field_instruction(field: etree._Element) -> str:
    return str(field.get(_qn("instr")) or field.get("w:instr") or "")


def _complex_fields(root: etree._Element) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for node in root.iter():
        if node.tag == _qn("fldChar"):
            field_type = str(node.get(_qn("fldCharType")) or "")
            if field_type == "begin":
                stack.append({"begin": node, "instruction_parts": [], "separate": None})
            elif field_type == "separate" and stack:
                stack[-1]["separate"] = node
            elif field_type == "end" and stack:
                field = stack.pop()
                field["end"] = node
                field["instruction"] = "".join(field.pop("instruction_parts", []))
                fields.append(field)
            continue
        if node.tag == _qn("instrText") and stack and stack[-1].get("separate") is None:
            stack[-1]["instruction_parts"].append(str(node.text or ""))
    return fields


def discover_structured_targets(docx_path: Path | str) -> list[dict[str, Any]]:
    """List selectable SDT controls and bookmarks in the template's visible parts."""

    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    with zipfile.ZipFile(Path(docx_path), "r") as archive:
        for part_name in _word_part_names(archive.namelist()):
            root = etree.fromstring(archive.read(part_name))
            part_label = _part_label(part_name)

            for sdt in root.xpath(".//w:sdt", namespaces=NS):
                tag = _sdt_value(sdt, "tag")
                alias = _sdt_value(sdt, "alias")
                if tag:
                    locator = f"SDT:{tag}"
                    label = f"内容控件（标记）{tag}"
                elif alias:
                    locator = f"SDT_ALIAS:{alias}"
                    label = f"内容控件（别名）{alias}"
                else:
                    continue
                content = sdt.find("w:sdtContent", namespaces=NS)
                key = ("content_control", locator)
                entry = candidates.setdefault(
                    key,
                    {
                        "target_kind": "content_control",
                        "target_locator": locator,
                        "label": label,
                        "preview": _short_preview(_text_of(content), "空内容控件"),
                        "locations": [],
                    },
                )
                entry["locations"].append(part_label)

            for field in root.xpath(".//w:fldSimple", namespaces=NS):
                field_name = _merge_field_name(_simple_field_instruction(field))
                if not field_name:
                    continue
                locator = f"FIELD:{field_name}"
                key = ("merge_field", locator)
                entry = candidates.setdefault(
                    key,
                    {
                        "target_kind": "merge_field",
                        "target_locator": locator,
                        "label": f"Word 合并字段 {field_name}",
                        "preview": _short_preview(_text_of(field), "空合并字段"),
                        "locations": [],
                    },
                )
                entry["locations"].append(part_label)

            for field in _complex_fields(root):
                field_name = _merge_field_name(str(field.get("instruction") or ""))
                separate = field.get("separate")
                end = field.get("end")
                if not field_name or not isinstance(separate, etree._Element) or not isinstance(end, etree._Element):
                    continue
                locator = f"FIELD:{field_name}"
                key = ("merge_field", locator)
                entry = candidates.setdefault(
                    key,
                    {
                        "target_kind": "merge_field",
                        "target_locator": locator,
                        "label": f"Word 合并字段 {field_name}",
                        "preview": _short_preview(_range_text(root, separate, end), "空合并字段"),
                        "locations": [],
                    },
                )
                entry["locations"].append(part_label)

            bookmark_ends = {
                str(end.get(_qn("id")) or ""): end
                for end in root.xpath(".//w:bookmarkEnd", namespaces=NS)
            }
            for start in root.xpath(".//w:bookmarkStart", namespaces=NS):
                name = str(start.get(_qn("name")) or "").strip()
                bookmark_id = str(start.get(_qn("id")) or "")
                end = bookmark_ends.get(bookmark_id)
                if not name or name.startswith("_") or end is None:
                    continue
                locator = f"BM:{name}"
                key = ("bookmark", locator)
                entry = candidates.setdefault(
                    key,
                    {
                        "target_kind": "bookmark",
                        "target_locator": locator,
                        "label": f"书签 {name}",
                        "preview": _short_preview(_range_text(root, start, end), "空书签"),
                        "locations": [],
                    },
                )
                entry["locations"].append(part_label)

    discovered: list[dict[str, Any]] = []
    for entry in candidates.values():
        locations = list(dict.fromkeys(entry.pop("locations", [])))
        if len(locations) > 1:
            entry["label"] = f"{entry['label']}（{len(locations)} 处）"
        elif locations:
            entry["label"] = f"{entry['label']}（{locations[0]}）"
        discovered.append(entry)
    return sorted(discovered, key=lambda item: (str(item["target_kind"]), str(item["target_locator"])))


def _preserve_spaces(text_element: etree._Element, value: str) -> None:
    if value.startswith(" ") or value.endswith(" "):
        text_element.set(XML_SPACE, "preserve")


def _append_visible_text(run: etree._Element, value: str) -> None:
    lines = value.splitlines() or [""]
    for index, line in enumerate(lines):
        if index:
            etree.SubElement(run, _qn("br"))
        text = etree.SubElement(run, _qn("t"))
        text.text = line
        _preserve_spaces(text, line)


def _first_run_properties(content: etree._Element) -> etree._Element | None:
    run_properties = content.find(".//w:rPr", namespaces=NS)
    return deepcopy(run_properties) if run_properties is not None else None


def _first_paragraph_properties(content: etree._Element) -> etree._Element | None:
    paragraph_properties = content.find(".//w:p/w:pPr", namespaces=NS)
    return deepcopy(paragraph_properties) if paragraph_properties is not None else None


def _set_content_control_text(sdt: etree._Element, value: str) -> bool:
    content = sdt.find("w:sdtContent", namespaces=NS)
    if content is None:
        return False
    run_properties = _first_run_properties(content)
    paragraph_properties = _first_paragraph_properties(content)
    block_level = bool(content.findall("w:p", namespaces=NS))
    for child in list(content):
        content.remove(child)
    if block_level:
        paragraph = etree.SubElement(content, _qn("p"))
        if paragraph_properties is not None:
            paragraph.append(paragraph_properties)
        run = etree.SubElement(paragraph, _qn("r"))
    else:
        run = etree.SubElement(content, _qn("r"))
    if run_properties is not None:
        run.append(run_properties)
    _append_visible_text(run, value)
    return True


def _content_control_matches(sdt: etree._Element, target: dict[str, Any]) -> bool:
    identity_kind = str(target.get("identity_kind") or "")
    identifier = str(target.get("identifier") or "")
    property_name = "tag" if identity_kind == "tag" else "alias"
    return _sdt_value(sdt, property_name) == identifier


def _find_bookmark_end(root: etree._Element, bookmark_id: str) -> etree._Element | None:
    matches = root.xpath(
        ".//w:bookmarkEnd[@w:id=$bookmark_id]",
        namespaces=NS,
        bookmark_id=bookmark_id,
    )
    return matches[0] if matches else None


def _bookmark_range_nodes(root: etree._Element, start: etree._Element, end: etree._Element) -> list[etree._Element] | None:
    nodes = list(root.iter())
    positions = {id(node): index for index, node in enumerate(nodes)}
    start_position = positions.get(id(start), -1)
    end_position = positions.get(id(end), -1)
    if start_position < 0 or end_position <= start_position:
        return None
    return nodes[start_position + 1 : end_position]


def _paragraph_ancestor(element: etree._Element) -> etree._Element | None:
    current: etree._Element | None = element
    while current is not None:
        if current.tag == _qn("p"):
            return current
        current = current.getparent()
    return None


def _paragraph_child_containing(paragraph: etree._Element, element: etree._Element) -> etree._Element | None:
    current = element
    while current.getparent() is not paragraph:
        parent = current.getparent()
        if parent is None:
            return None
        current = parent
    return current


def _replace_marker_range_text(root: etree._Element, start: etree._Element, end: etree._Element, value: str) -> bool:
    range_nodes = _bookmark_range_nodes(root, start, end)
    if range_nodes is None:
        return False
    run_properties = None
    text_nodes: list[etree._Element] = []
    for node in range_nodes:
        if run_properties is None and node.tag == _qn("r"):
            candidate = node.find("w:rPr", namespaces=NS)
            if candidate is not None:
                run_properties = deepcopy(candidate)
        if node.tag == _qn("t"):
            text_nodes.append(node)

    paragraph = _paragraph_ancestor(start)
    if paragraph is None:
        return False
    anchor = _paragraph_child_containing(paragraph, start)
    if anchor is None:
        return False

    for text_node in text_nodes:
        text_node.text = ""
    run = etree.Element(_qn("r"))
    if run_properties is not None:
        run.append(run_properties)
    _append_visible_text(run, value)
    paragraph.insert(paragraph.index(anchor) + 1, run)
    return True


def _fill_content_controls(root: etree._Element, target: dict[str, Any], value: str) -> int:
    return sum(
        1
        for sdt in root.xpath(".//w:sdt", namespaces=NS)
        if _content_control_matches(sdt, target) and _set_content_control_text(sdt, value)
    )


def _fill_bookmarks(root: etree._Element, target: dict[str, Any], value: str) -> int:
    name = str(target.get("bookmark_name") or "")
    updated = 0
    starts = list(root.xpath(".//w:bookmarkStart", namespaces=NS))
    for start in starts:
        if str(start.get(_qn("name")) or "") != name:
            continue
        end = _find_bookmark_end(root, str(start.get(_qn("id")) or ""))
        if end is not None and _replace_marker_range_text(root, start, end, value):
            updated += 1
    return updated


def _set_simple_field_result(field: etree._Element, value: str) -> bool:
    run_properties = _first_run_properties(field)
    for child in list(field):
        field.remove(child)
    run = etree.SubElement(field, _qn("r"))
    if run_properties is not None:
        run.append(run_properties)
    _append_visible_text(run, value)
    field.set(_qn("fldLock"), "true")
    field.set(_qn("dirty"), "false")
    return True


def _set_complex_field_result(root: etree._Element, field: dict[str, Any], value: str) -> bool:
    begin = field.get("begin")
    separate = field.get("separate")
    end = field.get("end")
    if not isinstance(begin, etree._Element) or not isinstance(separate, etree._Element) or not isinstance(end, etree._Element):
        return False
    if not _replace_marker_range_text(root, separate, end, value):
        return False
    begin.set(_qn("fldLock"), "true")
    begin.set(_qn("dirty"), "false")
    return True


def _fill_merge_fields(root: etree._Element, target: dict[str, Any], value: str) -> int:
    field_name = str(target.get("field_name") or "")
    updated = 0
    for field in root.xpath(".//w:fldSimple", namespaces=NS):
        if _merge_field_name(_simple_field_instruction(field)) == field_name and _set_simple_field_result(field, value):
            updated += 1
    for field in _complex_fields(root):
        if _merge_field_name(str(field.get("instruction") or "")) == field_name and _set_complex_field_result(root, field, value):
            updated += 1
    return updated


def apply_structured_target_values(docx_path: Path | str, entries: list[dict[str, Any]]) -> None:
    """Patch configured SDTs and bookmarks into an already-saved DOCX report."""

    active_entries = [entry for entry in entries if str(entry.get("target", {}).get("target_kind") or "") in {"content_control", "bookmark", "merge_field"}]
    if not active_entries:
        return

    report_path = Path(docx_path)
    with zipfile.ZipFile(report_path, "r") as archive:
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}

    roots = {
        part_name: etree.fromstring(payloads[part_name])
        for part_name in _word_part_names(payloads.keys())
    }
    missing: list[str] = []
    for entry in active_entries:
        target = dict(entry.get("target") or {})
        value = str(entry.get("value") or "")
        target_kind = str(target.get("target_kind") or "")
        updated = 0
        for root in roots.values():
            if target_kind == "content_control":
                updated += _fill_content_controls(root, target, value)
            elif target_kind == "bookmark":
                updated += _fill_bookmarks(root, target, value)
            elif target_kind == "merge_field":
                updated += _fill_merge_fields(root, target, value)
        if not updated:
            label = str(entry.get("label") or "填写位").strip()
            locator = str(entry.get("target_locator") or "").strip()
            missing.append(f"{label} ({locator})")

    if missing:
        raise ValueError(f"无法在导出模板中定位结构化填写位：{'; '.join(missing)}")

    for part_name, root in roots.items():
        payloads[part_name] = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{report_path.stem}_",
            suffix=".docx",
            dir=report_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        with zipfile.ZipFile(temporary_path, "w") as archive:
            for info in infos:
                archive.writestr(info, payloads[info.filename])
        os.replace(temporary_path, report_path)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
