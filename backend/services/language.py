from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from ..database import get_connection, transaction
from ..repositories.catalog import get_rule_pack, get_setting, set_setting
from ..repositories.visits import get_visit


DEFAULT_ADAPTER_CONFIG = {
    "provider": "deterministic",
    "base_url": "",
    "model": "",
    "enabled": False,
}

DEFAULT_TERMINOLOGY = {
    "ICF": "知情同意书（ICF）",
    "SAE": "严重不良事件（SAE）",
    "AE": "不良事件（AE）",
    "CRF": "病例报告表（CRF）",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# PRD 9.8/11.4: "当系统检测到数字、日期、版本、受试者编号、专有名词、否定词、范围词、责任主体或
# 结论发生变化时，阻止接受并要求重新生成或人工改写". The current adapter is a deterministic,
# non-generative rewriter (whitespace/terminology/fixed-phrase substitution only), so it cannot
# itself invent new facts — but a misconfigured rule-pack preferred_phrase mapping could still
# silently swap a negation or a number, and this is also the safety net PRD 11.9 requires to
# already exist before a real LLM ever replaces the deterministic adapter. It only gates the
# "accept the machine-proposed text as-is" path; "edited" (CRA manually retypes the text) is the
# PRD's own escape valve ("要求重新生成或人工改写") and is not blocked here.
_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")
_DATE_PATTERN = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?")
_VERSION_PATTERN = re.compile(r"[Vv]\d+(?:\.\d+)*")
_SUBJECT_CODE_PATTERN = re.compile(r"\b\d{2,4}-\d{2,4}\b")
_NEGATION_WORDS = ("不", "未", "无", "没有", "拒绝", "并非", "并未", "未见", "未发现", "不适用", "不符合")


def _token_counts(text: str, pattern: re.Pattern[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in pattern.findall(text):
        counts[match] = counts.get(match, 0) + 1
    return counts


def detect_high_risk_language_diff(original_text: str, proposed_text: str) -> list[str]:
    """Return a list of human-readable reasons the diff should be blocked, or [] if safe."""
    reasons: list[str] = []
    checks: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("数字/百分比", _NUMBER_PATTERN),
        ("日期", _DATE_PATTERN),
        ("版本号", _VERSION_PATTERN),
        ("受试者编号格式片段", _SUBJECT_CODE_PATTERN),
    )
    for label, pattern in checks:
        if _token_counts(original_text, pattern) != _token_counts(proposed_text, pattern):
            reasons.append(f"{label}发生变化")

    original_negations = {word: original_text.count(word) for word in _NEGATION_WORDS if word in original_text}
    proposed_negations = {word: proposed_text.count(word) for word in _NEGATION_WORDS if word in proposed_text}
    if original_negations != proposed_negations:
        reasons.append("否定/范围词发生变化")

    return reasons


def _row(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _audit(
    connection,
    *,
    project_id: str,
    visit_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_name: str,
    detail: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            project_id,
            visit_id,
            entity_type,
            entity_id,
            action,
            actor_name,
            json.dumps(detail, ensure_ascii=False),
            _now(),
        ),
    )


def get_adapter_config() -> dict[str, Any]:
    raw = get_setting("language_adapter_config", "")
    try:
        stored = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        stored = {}
    config = {**DEFAULT_ADAPTER_CONFIG, **stored}
    config["enabled"] = bool(config.get("enabled", False))
    config["network_calls"] = False
    config["status_note"] = "当前演示仅使用本地确定性适配器；不会向任何外部模型发送数据。"
    return config


def update_adapter_config(patch: dict[str, Any]) -> dict[str, Any]:
    current = get_adapter_config()
    config = {
        "provider": str(patch.get("provider", current["provider"])).strip() or "deterministic",
        "base_url": str(patch.get("base_url", current["base_url"])).strip(),
        "model": str(patch.get("model", current["model"])).strip(),
        "enabled": bool(patch.get("enabled", current["enabled"])),
    }
    set_setting("language_adapter_config", json.dumps(config, ensure_ascii=False))
    return get_adapter_config()


def _frozen_rule_pack(visit: dict[str, Any]) -> dict[str, Any]:
    snapshot_rule = dict((visit.get("snapshot") or {}).get("rule_pack") or {})
    live_rule = get_rule_pack(visit["rule_pack_id"]) or {}
    if not snapshot_rule:
        return live_rule
    if not snapshot_rule.get("content"):
        snapshot_rule["content"] = live_rule.get("content", {})
    return {**live_rule, **snapshot_rule}


def _terminology(rule_pack: dict[str, Any]) -> dict[str, str]:
    content = rule_pack.get("content") or {}
    configured = content.get("terminology") if isinstance(content, dict) else {}
    if not isinstance(configured, dict):
        configured = {}
    return {
        **DEFAULT_TERMINOLOGY,
        **{str(key).strip(): str(value).strip() for key, value in configured.items() if str(key).strip() and str(value).strip()},
    }


def _preferred_phrases(rule_pack: dict[str, Any]) -> list[tuple[str, str]]:
    content = rule_pack.get("content") or {}
    language_rules = content.get("language_rules") if isinstance(content, dict) else {}
    configured = language_rules.get("preferred_phrases") if isinstance(language_rules, dict) else []
    if not isinstance(configured, list):
        return []
    phrases: list[tuple[str, str]] = []
    for item in configured:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if source and target and source != target:
            phrases.append((source, target))
    return phrases


class DeterministicLanguageAdapter:
    """A local presentation adapter that is deliberately unable to add clinical facts."""

    name = "deterministic"

    def propose(
        self,
        original_text: str,
        terminology: dict[str, str],
        preferred_phrases: list[tuple[str, str]],
    ) -> dict[str, str]:
        proposed = original_text.strip()
        summaries: list[str] = []

        normalized = re.sub(r"\s+", " ", proposed)
        normalized = re.sub(r"\s+([，。；：、])", r"\1", normalized)
        if normalized != proposed:
            proposed = normalized
            summaries.append("规范空白与标点间距")

        expanded: list[str] = []
        for short_name, canonical_name in sorted(terminology.items(), key=lambda item: len(item[0]), reverse=True):
            if canonical_name in proposed:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(short_name)}(?![A-Za-z0-9])")
            if pattern.search(proposed):
                proposed = pattern.sub(canonical_name, proposed)
                expanded.append(short_name)
        if expanded:
            summaries.append("按规则包统一术语：" + "、".join(expanded))

        replaced: list[str] = []
        for source, target in sorted(preferred_phrases, key=lambda item: len(item[0]), reverse=True):
            if source not in proposed:
                continue
            proposed = proposed.replace(source, target)
            replaced.append(source)
        if replaced:
            summaries.append("按规则包采用固定表述：" + "、".join(replaced))

        return {
            "original_text": original_text,
            "proposed_text": proposed,
            "change_summary": "；".join(summaries) or "无需调整",
        }


def list_language_suggestions(visit_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT ls.*, cf.target_table, cf.field_key, cf.category, cf.subject_code,
                   cf.source_record_id, cf.suggestion_id
            FROM language_suggestions ls
            JOIN confirmed_fields cf ON cf.id = ls.confirmed_field_id
            WHERE ls.visit_id = ? AND cf.is_active = 1
            ORDER BY ls.created_at DESC, ls.rowid DESC
            """,
            (visit_id,),
        ).fetchall()
    items = [dict(row) for row in rows]
    resolved_fields = {
        item["confirmed_field_id"]
        for item in items
        if item["status"] in {"accepted", "edited"}
    }
    return [
        item
        for item in items
        if not (item["status"] == "pending" and item["confirmed_field_id"] in resolved_fields)
    ]


def effective_language_by_field(visit_id: str) -> dict[str, dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT language_suggestion.*
            FROM language_suggestions language_suggestion
            JOIN confirmed_fields confirmed_field ON confirmed_field.id = language_suggestion.confirmed_field_id
            WHERE language_suggestion.visit_id = ?
              AND language_suggestion.status IN ('accepted', 'edited')
              AND confirmed_field.is_active = 1
            ORDER BY language_suggestion.decided_at DESC, language_suggestion.rowid DESC
            """,
            (visit_id,),
        ).fetchall()
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        selected.setdefault(item["confirmed_field_id"], item)
    return selected


def generate_language_suggestions(*, visit_id: str, actor_name: str) -> list[dict[str, Any]]:
    visit = get_visit(visit_id)
    if visit is None:
        raise ValueError("未找到当前访视")
    rule_pack = _frozen_rule_pack(visit)
    adapter = DeterministicLanguageAdapter()
    created: list[dict[str, Any]] = []
    timestamp = _now()

    with transaction() as connection:
        confirmed_fields = connection.execute(
            "SELECT * FROM confirmed_fields WHERE visit_id = ? AND is_active = 1 "
            "AND assertion_type <> 'center_explanation' AND source_type <> 'center_explanation' "
            "ORDER BY confirmed_at ASC, rowid ASC",
            (visit_id,),
        ).fetchall()
        for confirmed_field in confirmed_fields:
            original_text = str(confirmed_field["value"] or "").strip()
            if not original_text:
                continue
            proposal = adapter.propose(
                original_text,
                _terminology(rule_pack),
                _preferred_phrases(rule_pack),
            )
            if proposal["proposed_text"] == original_text:
                continue
            existing = connection.execute(
                """
                SELECT id FROM language_suggestions
                WHERE confirmed_field_id = ? AND original_text = ?
                """,
                (confirmed_field["id"], original_text),
            ).fetchone()
            if existing is not None:
                continue
            suggestion_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO language_suggestions (
                    id, visit_id, confirmed_field_id, rule_pack_id, original_text, proposed_text,
                    change_summary, status, final_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', '', ?)
                """,
                (
                    suggestion_id,
                    visit_id,
                    confirmed_field["id"],
                    rule_pack.get("id") or visit["rule_pack_id"],
                    original_text,
                    proposal["proposed_text"],
                    proposal["change_summary"],
                    timestamp,
                ),
            )
            _audit(
                connection,
                project_id=visit["project_id"],
                visit_id=visit_id,
                entity_type="language_suggestion",
                entity_id=suggestion_id,
                action="generated",
                actor_name=actor_name,
                detail={
                    "confirmed_field_id": confirmed_field["id"],
                    "adapter": adapter.name,
                    "rule_pack_version": rule_pack.get("version", ""),
                    "change_summary": proposal["change_summary"],
                },
            )
            created.append(
                {
                    "id": suggestion_id,
                    "visit_id": visit_id,
                    "confirmed_field_id": confirmed_field["id"],
                    "rule_pack_id": rule_pack.get("id") or visit["rule_pack_id"],
                    **proposal,
                    "status": "pending",
                    "final_text": "",
                    "created_at": timestamp,
                }
            )
    return created


def decide_language_suggestion(
    *,
    visit_id: str,
    suggestion_id: str,
    decision: Literal["accepted", "edited", "rejected"],
    actor_name: str,
    edited_text: str | None = None,
) -> dict[str, Any]:
    timestamp = _now()
    with transaction() as connection:
        visit_row = connection.execute("SELECT project_id FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if visit_row is None:
            raise ValueError("未找到当前访视")
        row = connection.execute(
            """
            SELECT language_suggestion.*
            FROM language_suggestions language_suggestion
            JOIN confirmed_fields confirmed_field ON confirmed_field.id = language_suggestion.confirmed_field_id
            WHERE language_suggestion.id = ?
              AND language_suggestion.visit_id = ?
              AND confirmed_field.is_active = 1
            """,
            (suggestion_id, visit_id),
        ).fetchone()
        if row is None:
            raise ValueError("未找到语言优化建议")
        if row["status"] != "pending":
            raise ValueError("该语言优化建议已处理")
        final_text = ""
        if decision in {"accepted", "edited"}:
            final_text = (edited_text if decision == "edited" else row["proposed_text"]).strip()
            if not final_text:
                raise ValueError("确认后的展示文本不能为空")
        if decision == "accepted":
            risk_reasons = detect_high_risk_language_diff(row["original_text"], row["proposed_text"])
            if risk_reasons:
                raise ValueError(
                    "检测到优化稿相对原文存在高风险差异（"
                    + "、".join(risk_reasons)
                    + "），已阻止一键接受；请核对差异后选择重新生成或改为人工改写"
                )
        connection.execute(
            """
            UPDATE language_suggestions
            SET status = ?, final_text = ?, decided_at = ?, decided_by = ?
            WHERE id = ?
            """,
            (decision, final_text, timestamp, actor_name, suggestion_id),
        )
        _audit(
            connection,
            project_id=visit_row["project_id"],
            visit_id=visit_id,
            entity_type="language_suggestion",
            entity_id=suggestion_id,
            action=decision,
            actor_name=actor_name,
            detail={"final_text": final_text, "confirmed_field_id": row["confirmed_field_id"]},
        )
        saved = connection.execute("SELECT * FROM language_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    return _row(saved) or {}


def revoke_language_suggestion(
    *,
    visit_id: str,
    suggestion_id: str,
    actor_name: str,
    reason: str,
) -> dict[str, Any]:
    revoke_reason = reason.strip()
    if not revoke_reason:
        raise ValueError("请填写撤销语言采用的原因")

    timestamp = _now()
    with transaction() as connection:
        visit_row = connection.execute("SELECT project_id FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if visit_row is None:
            raise ValueError("未找到当前访视")
        row = connection.execute(
            """
            SELECT language_suggestion.*
            FROM language_suggestions language_suggestion
            JOIN confirmed_fields confirmed_field ON confirmed_field.id = language_suggestion.confirmed_field_id
            WHERE language_suggestion.id = ?
              AND language_suggestion.visit_id = ?
              AND confirmed_field.is_active = 1
            """,
            (suggestion_id, visit_id),
        ).fetchone()
        if row is None:
            raise ValueError("未找到语言优化建议")
        if row["status"] not in {"accepted", "edited"}:
            raise ValueError("只有已采用的语言优化建议可以撤销")

        connection.execute(
            """
            UPDATE language_suggestions
            SET status = 'revoked', revoked_at = ?, revoked_by = ?, revoke_reason = ?
            WHERE id = ?
            """,
            (timestamp, actor_name, revoke_reason, suggestion_id),
        )
        _audit(
            connection,
            project_id=visit_row["project_id"],
            visit_id=visit_id,
            entity_type="language_suggestion",
            entity_id=suggestion_id,
            action="revoked",
            actor_name=actor_name,
            detail={
                "confirmed_field_id": row["confirmed_field_id"],
                "previous_status": row["status"],
                "previous_final_text": row["final_text"],
                "reason": revoke_reason,
            },
        )
        saved = connection.execute("SELECT * FROM language_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    return _row(saved) or {}
