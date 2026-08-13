from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parent
STATE_PATH = BACKEND_DIR / "data" / "demo_state.json"
_LOCK = RLock()


def build_seed_state() -> dict[str, Any]:
    """Return a deliberately de-identified, single-project demo workspace."""
    table_titles = [
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
    initial_status = {
        1: ("已映射", "项目固定信息已载入"),
        2: ("已映射", "本次首例筛选监查访视"),
        3: ("待补录", "可由 CRA 记录或 AI 建议补充"),
        4: ("已映射", "招募数字可直接编辑"),
        5: ("待补录", "待 CRA 确认本次监查范围"),
    }
    tasks = []
    for index, title in enumerate(table_titles, start=1):
        status, evidence = initial_status.get(index, ("待补录", "待 CRA 记录或确认"))
        tasks.append(
            {
                "id": f"table-{index}",
                "index": index,
                "title": title,
                "status": status,
                "evidence": evidence,
            }
        )

    return {
        "project": {
            "study_name": "UA007-GT02 首例筛选监查访视（演示）",
            "study_id": "UA007-GT02",
            "site_name": "示例研究中心",
            "pi_name": "示例主要研究者",
            "sponsor": "示例申办方",
            "approval_number": "示例批件号",
            "protocol_version": "方案 V1.2 / 2026-07-16",
            "icf_version": "ICF V1.1 / 2026-07-16",
            "ethics_date": "伦理批准：2026-07-20",
            "sop_version": "常规监查访视 SOP V1.0",
        },
        "visit": {
            "visit_type": "首例筛选监查访视",
            "visit_date": "2026-08-26",
            "report_date": "2026-08-26",
            "site_team": "示例 CRC、研究护士",
            "monitoring_team": "演示 CRA",
            "next_visit": "待 CRA 与中心确认",
            "cra_name": "演示 CRA",
        },
        "recruitment": {
            "screened": 1,
            "screen_failed": 0,
            "treated": 0,
            "ae_dropout": 0,
            "other_dropout": 0,
            "completed_treatment": 0,
            "follow_up": 0,
            "follow_up_dropout": 0,
            "completed_follow_up": 0,
        },
        "table_tasks": tasks,
        "records": [],
        "suggestions": [],
        "confirmed_items": [],
        "ae_records": [],
        "deviations": [],
        "action_items": [],
        "review_comments": [],
        "report_status": "draft",
        "last_generated_at": None,
        "last_generated_file": None,
        "last_submitted_at": None,
    }


def load_state() -> dict[str, Any]:
    from .database import initialize_database

    initialize_database()
    with _LOCK:
        if not STATE_PATH.exists():
            state = build_seed_state()
            save_state(state)
            return state
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not state.get("table_tasks"):
            state["table_tasks"] = build_seed_state()["table_tasks"]
            save_state(state)
        return state


def save_state(state: dict[str, Any]) -> None:
    with _LOCK:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def reset_state() -> dict[str, Any]:
    from .database import reset_database

    reset_database()
    state = deepcopy(build_seed_state())
    save_state(state)
    return state
