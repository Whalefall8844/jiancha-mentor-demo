from __future__ import annotations

import re
import unicodedata
from typing import Any


MATCHING_ALGORITHM = "template_keyword_v1"


VISIT_TYPE_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "code": "first_subject_screening",
        "label": "首例筛选监查访视",
        "aliases": ("首例筛选监查访视", "首例筛选监查", "首例筛选访视", "首例筛选", "first subject screening"),
        "weight": 78,
    },
    {
        "code": "first_subject_dosing",
        "label": "首例入组/给药监查访视",
        "aliases": ("首例入组监查", "首例入组", "首例给药", "first subject dosed", "first patient in"),
        "weight": 76,
    },
    {
        "code": "site_initiation",
        "label": "启动访视（SIV）",
        "aliases": ("启动访视", "中心启动", "研究启动", "siv", "site initiation"),
        "weight": 74,
    },
    {
        "code": "closeout",
        "label": "关闭访视（COV）",
        "aliases": ("关闭访视", "中心关闭", "结束访视", "cov", "close out", "closeout"),
        "weight": 74,
    },
    {
        "code": "remote_monitoring",
        "label": "远程监查访视",
        "aliases": ("远程监查", "远程访视", "remote monitoring", "rmv"),
        "weight": 68,
    },
    {
        "code": "screening_visit",
        "label": "筛选访视（SSV）",
        "aliases": ("筛选访视", "筛选监查", "ssv", "screening visit"),
        "weight": 62,
        "generic": True,
    },
    {
        "code": "routine_imv",
        "label": "常规监查访视（IMV）",
        "aliases": ("常规监查", "监查访视", "imv", "interim monitoring", "monitoring visit"),
        "weight": 58,
        "generic": True,
    },
)


def _normalise(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_visit_type_keywords(values: object) -> list[str]:
    if isinstance(values, str):
        candidates = re.split(r"[,，;；\n\r]+", values)
    elif isinstance(values, (list, tuple)):
        candidates = [str(value) for value in values]
    else:
        candidates = []
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        value = " ".join(candidate.split()).strip()
        normalised = _normalise(value)
        if value and normalised and normalised not in seen:
            seen.add(normalised)
            result.append(value)
    return result


def _administrator_keywords(template: dict[str, Any]) -> list[str]:
    metadata = template.get("metadata") or {}
    return normalize_visit_type_keywords(metadata.get("visit_type_keywords", []))


def _source_parts(template: dict[str, Any], detected_tables: list[dict[str, Any]] | None = None) -> list[str]:
    metadata = template.get("metadata") or {}
    parts = [str(template.get("name") or ""), str(metadata.get("source_file_name") or "")]
    for table in detected_tables or metadata.get("detected_tables") or []:
        parts.append(str(table.get("detected_label") or ""))
    return [part for part in parts if part.strip()]


def build_matching_profile(template: dict[str, Any], detected_tables: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Infer visit-type hints from user-visible template metadata without calling a model."""
    source_parts = _source_parts(template, detected_tables)
    source_text = " ".join(source_parts)
    normalised_source = _normalise(source_text)
    administrator_keywords = _administrator_keywords(template)
    matched_profiles: list[dict[str, Any]] = []

    for profile in VISIT_TYPE_PROFILES:
        source_terms = [
            alias
            for alias in profile["aliases"]
            if _normalise(alias) and _normalise(alias) in normalised_source
        ]
        administrator_terms = [
            keyword
            for keyword in administrator_keywords
            if any(
                _normalise(alias)
                and (_normalise(alias) in _normalise(keyword) or _normalise(keyword) in _normalise(alias))
                for alias in profile["aliases"]
            )
        ]
        matched_terms = _unique(source_terms + administrator_terms)
        if matched_terms:
            matched_profiles.append(
                {
                    "code": profile["code"],
                    "label": profile["label"],
                    "matched_terms": _unique(matched_terms),
                }
            )

    profile_definitions = {profile["code"]: profile for profile in VISIT_TYPE_PROFILES}
    specific_codes = {profile["code"] for profile in matched_profiles if not profile_definitions[profile["code"]].get("generic")}
    if specific_codes:
        matched_profiles = [
            profile
            for profile in matched_profiles
            if not profile_definitions[profile["code"]].get("generic")
        ]

    return {
        "algorithm": MATCHING_ALGORITHM,
        "inferred_visit_types": matched_profiles,
        "matched_terms": _unique([term for profile in matched_profiles for term in profile["matched_terms"]]),
        "administrator_keywords": administrator_keywords,
    }


def _profile_by_code(code: str) -> dict[str, Any] | None:
    return next((profile for profile in VISIT_TYPE_PROFILES if profile["code"] == code), None)


def _confidence(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def recommend_templates(templates: list[dict[str, Any]], visit_type: str) -> dict[str, Any]:
    """Rank active report templates for a CRA-entered visit type using explainable rules."""
    target_text = visit_type.strip()
    target_profile = build_matching_profile({"name": target_text})
    target_codes = {item["code"] for item in target_profile["inferred_visit_types"]}
    normalised_target = _normalise(target_text)
    recommendations: list[dict[str, Any]] = []

    for item in templates:
        template = item["template"] if "template" in item else item
        profile = item.get("matching_profile") or build_matching_profile(template, item.get("detected_tables"))
        source_text = " ".join(_source_parts(template, item.get("detected_tables")))
        normalised_source = _normalise(source_text)
        candidate_codes = {entry["code"] for entry in profile["inferred_visit_types"]}
        matched_terms: list[str] = []
        reasons: list[str] = []
        score = 0

        administrator_matches = [
            keyword
            for keyword in profile.get("administrator_keywords", [])
            if normalised_target
            and _normalise(keyword)
            and (_normalise(keyword) in normalised_target or normalised_target in _normalise(keyword))
        ]
        if administrator_matches:
            score = 92
            matched_terms.extend(administrator_matches)
            reasons.append("模板管理员已确认该模板适用于当前访视类型")

        for entry in target_profile["inferred_visit_types"]:
            if entry["code"] not in candidate_codes:
                continue
            definition = _profile_by_code(entry["code"])
            if definition is None:
                continue
            candidate_entry = next(value for value in profile["inferred_visit_types"] if value["code"] == entry["code"])
            score = max(score, int(definition["weight"]))
            shared_terms = _unique(entry["matched_terms"] + candidate_entry["matched_terms"])
            matched_terms.extend(shared_terms)
            reasons.append(f"访视类型与模板特征“{definition['label']}”一致")

        if normalised_target and len(normalised_target) >= 3 and normalised_target in normalised_source:
            score += 20
            reasons.append("模板名称、源文件名或表格标题直接包含当前访视类型")

        if not target_codes:
            matching_chars = len(set(normalised_target) & set(normalised_source)) if normalised_target else 0
            if matching_chars >= 2:
                score += min(35, matching_chars * 8)
                reasons.append("模板文字与当前访视类型存在可见关键词重合")

        if score == 0:
            reasons.append("未识别到特异访视类型，请由 CRA 复核后手工选择")
        else:
            reasons.append("仅基于已上传模板的名称和表格结构特征计算，不改写 CRA 的选择")

        recommendations.append(
            {
                "template": template,
                "matching_profile": profile,
                "score": min(score, 100),
                "confidence": _confidence(min(score, 100)),
                "matched_terms": _unique(matched_terms),
                "reasons": reasons,
            }
        )

    recommendations.sort(key=lambda item: (-item["score"], item["template"]["name"], item["template"]["version"]))
    top = recommendations[0] if recommendations else None
    return {
        "visit_type": target_text,
        "recommended_template_id": top["template"]["id"] if top else "",
        "auto_selectable": bool(top and top["score"] >= 75),
        "items": recommendations,
    }
