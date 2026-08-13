from __future__ import annotations

import re
import unicodedata
from typing import Any


MAPPING_SUGGESTION_ALGORITHM = "template_mapping_keyword_v1"


MAPPING_PROFILES: tuple[dict[str, Any], ...] = (
    {"field_key": "overall_assessment", "target_description": "监查总体评价与结论", "terms": ("总体评价", "总体结论", "监查总结", "监查结论", "总结与建议")},
    {"field_key": "findings_actions", "target_description": "监查发现、整改与行动项跟踪", "terms": ("监查发现", "行动项", "整改跟踪", "问题及建议", "问题跟踪", "问题整改")},
    {"field_key": "informed_consent", "target_description": "知情同意过程与版本核查", "terms": ("知情同意", "知情同意书", "icf")},
    {"field_key": "ethics_compliance", "target_description": "伦理审查与持续合规核查", "terms": ("伦理委员会", "伦理审查", "伦理", "irb", "ec")},
    {"field_key": "protocol_compliance", "target_description": "方案执行、依从性与方案偏离核查", "terms": ("方案偏离", "方案依从", "方案执行", "protocol")},
    {"field_key": "safety", "target_description": "安全性信息（AE/SAE）核查", "terms": ("严重不良事件", "不良事件", "安全性", "sae", "ae")},
    {"field_key": "investigational_product", "target_description": "试验用药品/药房管理核查", "terms": ("试验用药", "研究药物", "药物管理", "药房", "ip管理", "ip")},
    {"field_key": "data_quality", "target_description": "数据录入、查询与 eCRF 核查", "terms": ("病例报告表", "数据核查", "数据管理", "数据录入", "查询", "edc", "ecrf")},
    {"field_key": "laboratory_samples", "target_description": "实验室、样本与检验管理核查", "terms": ("实验室", "生物样本", "样本管理", "检验", "样本")},
    {"field_key": "systems_equipment", "target_description": "系统、设备与关键记录核查", "terms": ("iwrs", "ixrs", "epro", "设备", "仪器", "校准", "温度", "系统")},
    {"field_key": "essential_documents", "target_description": "研究文件与必备文件核查", "terms": ("研究者文件", "必备文件", "文件管理", "文件归档", "isf", "tmf")},
    {"field_key": "site_team", "target_description": "研究团队、授权与职责履行核查", "terms": ("人员资质", "研究团队", "研究人员", "研究者授权", "主要研究者", "pi")},
    {"field_key": "subject_progress", "target_description": "受试者筛选、入组与随访进展核查", "terms": ("受试者筛选", "筛选情况", "入组情况", "受试者", "招募", "脱落")},
    {"field_key": "site_visit_overview", "target_description": "中心与本次监查基本情况", "terms": ("监查基本信息", "中心基本情况", "研究中心基本情况", "访视基本信息", "项目基本信息")},
    {"field_key": "next_visit_plan", "target_description": "后续工作与下次访视计划", "terms": ("下次访视", "后续计划", "后续安排", "下一步计划")},
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


def _profile_for_label(label: str) -> tuple[dict[str, Any] | None, list[str]]:
    normalized_label = _normalise(label)
    best_profile: dict[str, Any] | None = None
    best_terms: list[str] = []
    best_score = 0
    for profile in MAPPING_PROFILES:
        matched_terms = [term for term in profile["terms"] if _normalise(term) and _normalise(term) in normalized_label]
        score = sum(len(_normalise(term)) for term in matched_terms)
        if score > best_score:
            best_profile = profile
            best_terms = matched_terms
            best_score = score
    return best_profile, _unique(best_terms)


def suggest_template_mappings(detected_tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Suggest task-area names from Word table titles without persisting any mapping."""
    used_keys: dict[str, int] = {}
    suggestions: list[dict[str, Any]] = []
    for table in detected_tables:
        table_index = int(table.get("table_index") or len(suggestions) + 1)
        label = str(table.get("detected_label") or f"表 {table_index}").strip()
        profile, matched_terms = _profile_for_label(label)
        if profile is None:
            base_key = f"table_{table_index}"
            target_description = label if label and label != f"表 {table_index}" else f"第 {table_index} 表监查内容"
            confidence = "low"
            reason = "未识别到明确临床监查关键词，保留表号型字段键并请管理员定义监查区域。"
        else:
            base_key = str(profile["field_key"])
            target_description = str(profile["target_description"])
            confidence = "high" if len(matched_terms) >= 2 or max((len(_normalise(term)) for term in matched_terms), default=0) >= 5 else "medium"
            reason = f"表格标题命中关键词：{'、'.join(matched_terms)}。"
        ordinal = used_keys.get(base_key, 0) + 1
        used_keys[base_key] = ordinal
        field_key = base_key if ordinal == 1 else f"{base_key}_{ordinal}"
        if ordinal > 1:
            reason += f" 同一监查区域已出现 {ordinal - 1} 次，字段键增加序号以保持独立。"
        suggestions.append({
            "table_index": table_index,
            "field_key": field_key,
            "target_description": target_description,
            "confidence": confidence,
            "matched_terms": matched_terms,
            "reason": reason,
            "algorithm": MAPPING_SUGGESTION_ALGORITHM,
        })
    return suggestions
