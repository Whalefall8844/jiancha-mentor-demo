from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4


def _subject_from_text(text: str) -> str:
    patterns = [
        r"(?:受试者(?:编号)?[：:\s]*)?([A-Za-z]{1,4}[-_]?\d{3,6})",
        r"(\d{3}[-_]\d{3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).upper()
    return "未提供受试者编号"


def _professional_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip().rstrip("。；;")
    return cleaned + "。"


def _make_suggestion(
    *, target_table: int, category: str, title: str, text: str, source: str, subject: str, source_type: str = "work_record"
) -> dict:
    has_subject = subject and subject != "未提供受试者编号"
    is_center_explanation = source_type == "center_explanation"
    assertion_type = "center_explanation" if is_center_explanation else "action_request" if category == "action" else "monitoring_summary" if category == "summary" else "reported_observation"
    return {
        "id": uuid4().hex,
        "target_table": target_table,
        "category": category,
        "title": title,
        "proposed_text": f"中心解释：{text}" if is_center_explanation else text,
        "source": source,
        "subject": subject,
        "value_type": "narrative",
        "assertion_type": assertion_type,
        "source_type": source_type,
        "evidence_text": source,
        "evidence_start": 0,
        "evidence_end": len(source),
        "entity_type": "subject" if has_subject else "visit",
        "entity_id": subject if has_subject else "",
        "pending_reason": "需 CRA 对照原始记录确认",
        "status": "pending",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def create_suggestions(record_text: str, *, source_type: str = "work_record") -> list[dict]:
    """A deterministic stand-in for the later real AI extraction service."""
    source = record_text.strip()
    normalized = _professional_text(source)
    lowered = source.lower()
    subject = _subject_from_text(source)
    suggestions: list[dict] = []

    if any(token in lowered for token in ("icf", "知情", "同意书")):
        suggestions.append(
            _make_suggestion(
                target_table=7,
                category="icf",
                title="知情同意过程核查",
                text=f"知情同意相关记录：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )
        if subject != "未提供受试者编号":
            suggestions.append(
                _make_suggestion(
                    target_table=8,
                    category="icf_list",
                    title="已签署 ICF 受试者列表",
                    text=f"{subject}：{normalized}",
                    source=source,
                    subject=subject,
                    source_type=source_type,
                )
            )

    if "sae" in lowered or "严重不良" in source or "不良事件" in source or re.search(r"(?<![a-z])ae(?![a-z])", lowered):
        is_sae = "sae" in lowered or "严重不良" in source
        suggestions.append(
            _make_suggestion(
                target_table=11,
                category="sae" if is_sae else "ae",
                title="AE / SAE 监查记录",
                text=f"{subject}：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    if any(token in source for token in ("方案偏离", "偏离", "违背", "漏检", "漏服", "超窗", "入排标准", "违例")):
        suggestions.append(
            _make_suggestion(
                target_table=13,
                category="deviation",
                title="方案偏离或违背",
                text=f"{subject}：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    if any(token in lowered for token in ("crf", "edc", "病例报告表", "原始病历")):
        suggestions.append(
            _make_suggestion(
                target_table=9,
                category="crf",
                title="CRF / 原始病历核查",
                text=f"CRF/原始记录核查：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    if any(token in source for token in ("招募", "入组", "筛选", "随机", "脱落", "受试者进展")):
        suggestions.append(
            _make_suggestion(
                target_table=4,
                category="recruitment",
                title="受试者筛选与招募进展",
                text=f"受试者进展相关记录：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    if any(token in source for token in ("药房", "研究药物", "试验用药", "药物管理", "发放", "回收", "库存", "温度记录")):
        suggestions.append(
            _make_suggestion(
                target_table=13,
                category="investigational_product",
                title="试验用药品／药房管理核查",
                text=f"试验用药品相关记录：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    if any(token in source for token in ("实验室", "样本", "资质", "归档", "存档", "授权", "培训", "履历", "研究者文件", "必备文件")):
        suggestions.append(
            _make_suggestion(
                target_table=12,
                category="document_archive",
                title="研究文件、人员资质或实验室资料核查",
                text=f"研究文件／资质相关记录：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    if any(token in lowered for token in ("iwrs", "ixrs", "epro", "系统", "设备", "仪器", "校准")):
        suggestions.append(
            _make_suggestion(
                target_table=5,
                category="system_device",
                title="系统／设备核查记录",
                text=f"系统／设备相关记录：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    if any(token in source for token in ("伦理", "方案版本", "ICF版本", "批件", "法规", "GCP", "研究者手册")):
        suggestions.append(
            _make_suggestion(
                target_table=6,
                category="regulatory",
                title="法规文件与版本核查",
                text=f"法规文件核查：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    if any(token in source for token in ("整改", "行动项", "需跟进", "需要跟进", "后续跟进", "后续安排", "请补充", "待完成")):
        suggestions.append(
            _make_suggestion(
                target_table=14,
                category="action",
                title="行动项与后续跟进",
                text=f"需跟进事项：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    if not suggestions:
        suggestions.append(
            _make_suggestion(
                target_table=3,
                category="summary",
                title="访视小结补充",
                text=f"本次监查记录：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )
    elif not any(item["target_table"] == 3 for item in suggestions):
        suggestions.append(
            _make_suggestion(
                target_table=3,
                category="summary",
                title="访视小结补充",
                text=f"本次监查记录：{normalized}",
                source=source,
                subject=subject,
                source_type=source_type,
            )
        )

    return suggestions
