from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .database import BACKEND_DIR, transaction


TABLE_TITLES = [
    "研究项目信息",
    "访视基本信息",
    "访视总体评价",
    "受试者招募情况",
    "监查摘要",
    "法规文件审查",
    "知情同意过程",
    "已签署 ICF 受试者列表",
    "病例报告表审阅",
    "已审核/回收 CRF 清单",
    "AE / SAE 报告",
    "文件审核与存档",
    "方案偏离及研究药品",
    "附加说明与行动项",
    "报告完成与审核信息",
]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _insert_tasks(connection, visit_id: str, created_at: str) -> None:
    initial_status = {
        1: ("已映射", "项目固定信息已载入"),
        2: ("已映射", "本次首例筛选监查访视"),
        3: ("待补录", "可由 CRA 记录或 AI 建议补充"),
        4: ("已映射", "招募数字可直接编辑"),
        5: ("待补录", "待 CRA 确认本次监查范围"),
    }
    for index, title in enumerate(TABLE_TITLES, start=1):
        status, evidence = initial_status.get(index, ("待补录", "待 CRA 记录或确认"))
        connection.execute(
            """
            INSERT INTO visit_tasks (id, visit_id, table_index, task_type, title, status, evidence, requires_evidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{visit_id}-task-{index}",
                visit_id,
                index,
                "template_table",
                title,
                status,
                evidence,
                1 if index in {7, 8, 11, 13, 14} else 0,
                created_at,
                created_at,
            ),
        )


def _insert_template_mappings(connection, template_id: str, created_at: str) -> None:
    for index, title in enumerate(TABLE_TITLES, start=1):
        connection.execute(
            """
            INSERT INTO template_mappings (id, template_id, table_index, field_key, target_description, required, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{template_id}-mapping-{index}",
                template_id,
                index,
                f"table_{index}",
                title,
                1 if index in {1, 2, 3, 4, 5, 15} else 0,
                created_at,
            ),
        )


def _insert_members(connection, project_id: str, members: Iterable[tuple[str, str]], created_at: str) -> None:
    for index, (name, role) in enumerate(members, start=1):
        connection.execute(
            "INSERT INTO project_members (id, project_id, display_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"{project_id}-member-{index}", project_id, name, role, created_at),
        )


def ensure_seed_data() -> None:
    with transaction() as connection:
        count = connection.execute("SELECT COUNT(*) AS count FROM projects").fetchone()["count"]
        if count:
            return

        created_at = now()
        template_path = str((BACKEND_DIR / "templates" / "ua007_gt02_template.docx").resolve())
        template_id = "template-ua007-imv-v1"
        connection.execute(
            """
            INSERT INTO templates (id, name, version, docx_path, table_count, metadata_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                "UA007-GT02 首例筛选监查访视报告",
                "V1.0",
                template_path,
                15,
                json.dumps({"source": "fixed_demo_template", "export_profile": "ua007_legacy_15_table", "table_count": 15}, ensure_ascii=False),
                "active",
                created_at,
                created_at,
            ),
        )
        _insert_template_mappings(connection, template_id, created_at)

        project_rows = [
            (
                "project-ua007",
                "UA007-GT02",
                "UA007 首例筛选监查（演示）",
                "示例申办方 A",
                {"approval_number": "示例批件号 A", "sop_version": "常规监查访视 SOP V1.0"},
            ),
            (
                "project-cm102",
                "CM102-IMV",
                "CM102 常规监查项目（演示）",
                "示例申办方 B",
                {"approval_number": "示例批件号 B", "sop_version": "常规监查访视 SOP V1.0"},
            ),
        ]
        for project_id, code, name, sponsor, metadata in project_rows:
            connection.execute(
                """
                INSERT INTO projects (id, code, name, sponsor, status, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (project_id, code, name, sponsor, json.dumps(metadata, ensure_ascii=False), created_at, created_at),
            )

        site_rows = [
            ("site-ua007-001", "project-ua007", "001", "示例研究中心 A", "示例主要研究者 A", "伦理批准：2026-07-20", "方案 V1.2 / 2026-07-16", "ICF V1.1 / 2026-07-16"),
            ("site-ua007-002", "project-ua007", "002", "示例研究中心 B", "示例主要研究者 B", "伦理批准：2026-07-22", "方案 V1.2 / 2026-07-16", "ICF V1.1 / 2026-07-16"),
            ("site-cm102-001", "project-cm102", "001", "CM102 示例研究中心", "示例主要研究者 C", "伦理批准：2026-07-18", "方案 V2.0 / 2026-07-12", "ICF V2.0 / 2026-07-12"),
        ]
        for row in site_rows:
            connection.execute(
                """
                INSERT INTO sites (id, project_id, code, name, pi_name, ethics_date, protocol_version, icf_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*row, created_at, created_at),
            )

        rule_packs = [
            (
                "rule-ua007-v1",
                "project-ua007",
                "UA007 IMV 规则包",
                "V1.0",
                {"task_template": "imv_15_table", "language_style": "cn_gcp", "terminology": {"ICF": "知情同意书（ICF）", "AE": "不良事件（AE）", "SAE": "严重不良事件（SAE）", "CRF": "病例报告表（CRF）"}},
            ),
            (
                "rule-cm102-v1",
                "project-cm102",
                "CM102 IMV 规则包",
                "V1.0",
                {"task_template": "imv_15_table", "language_style": "cn_gcp", "terminology": {"ICF": "知情同意书（ICF）", "AE": "不良事件（AE）", "SAE": "严重不良事件（SAE）", "CRF": "病例报告表（CRF）"}},
            ),
        ]
        rule_pack_snapshots = {}
        for rule_id, project_id, name, version, content in rule_packs:
            rule_pack_snapshots[rule_id] = {
                "id": rule_id,
                "name": name,
                "version": version,
                "effective_from": "2026-07-01",
                "effective_to": "",
                "content": content,
            }
            connection.execute(
                """
                INSERT INTO rule_packs (id, project_id, name, version, effective_from, effective_to, content_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    rule_id,
                    project_id,
                    name,
                    version,
                    "2026-07-01",
                    "",
                    json.dumps(content, ensure_ascii=False),
                    created_at,
                    created_at,
                ),
            )

        visits = [
            ("visit-ua007-001-imv", "project-ua007", "site-ua007-001", "rule-ua007-v1", "IMV-20260826", "首例筛选监查访视", "2026-08-26", "2026-08-26", "示例 CRC、研究护士", "演示 CRA", "待 CRA 与中心确认", "演示 CRA"),
            ("visit-ua007-002-imv", "project-ua007", "site-ua007-002", "rule-ua007-v1", "IMV-20260908", "常规监查访视", "2026-09-08", "2026-09-08", "示例 CRC", "演示 CRA", "待确认", "演示 CRA"),
            ("visit-cm102-001-imv", "project-cm102", "site-cm102-001", "rule-cm102-v1", "IMV-20260830", "常规监查访视", "2026-08-30", "2026-08-30", "示例研究护士", "演示 CRA", "待确认", "演示 CRA"),
        ]
        for visit in visits:
            visit_id, project_id, site_id, rule_pack_id, code, visit_type, visit_date, report_date, site_team, monitoring_team, next_visit, cra_name = visit
            snapshot = {
                "template_id": template_id,
                "rule_pack_id": rule_pack_id,
                "rule_pack": rule_pack_snapshots[rule_pack_id],
                "frozen_at": created_at,
            }
            connection.execute(
                """
                INSERT INTO visits (id, project_id, site_id, template_id, rule_pack_id, code, visit_type, visit_date, report_date, site_team, monitoring_team, next_visit, cra_name, snapshot_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    visit_id,
                    project_id,
                    site_id,
                    template_id,
                    rule_pack_id,
                    code,
                    visit_type,
                    visit_date,
                    report_date,
                    site_team,
                    monitoring_team,
                    next_visit,
                    cra_name,
                    json.dumps(snapshot, ensure_ascii=False),
                    created_at,
                    created_at,
                ),
            )
            _insert_tasks(connection, visit_id, created_at)

        subject_rows = [
            ("subject-ua007-001", "site-ua007-001", "S-DEMO-001", "screening"),
            ("subject-ua007-002", "site-ua007-001", "S-DEMO-002", "screening"),
            ("subject-ua007-003", "site-ua007-002", "S-DEMO-101", "screening"),
            ("subject-cm102-001", "site-cm102-001", "CM-DEMO-001", "enrolled"),
        ]
        for subject_id, site_id, code, status in subject_rows:
            connection.execute(
                """
                INSERT INTO subject_codes (id, site_id, code, enrollment_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (subject_id, site_id, code, status, created_at, created_at),
            )

        _insert_members(connection, "project-ua007", [("演示 CRA", "CRA"), ("演示 PM", "PM_LM"), ("演示管理员", "PROJECT_ADMIN"), ("演示医学监察/DM", "MEDICAL_DATA_REVIEWER")], created_at)
        _insert_members(connection, "project-cm102", [("演示 CRA", "CRA"), ("演示 PM", "PM_LM"), ("演示管理员", "PROJECT_ADMIN"), ("演示医学监察/DM", "MEDICAL_DATA_REVIEWER")], created_at)

        connection.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("current_visit_id", "visit-ua007-001-imv", created_at),
        )
        connection.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("current_role", "CRA", created_at),
        )
