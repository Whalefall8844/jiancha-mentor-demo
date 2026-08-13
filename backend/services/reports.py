from __future__ import annotations

import hashlib
from typing import Any

from ..repositories.visits import (
    create_audit_event,
    create_report_revision,
    list_revisions,
    next_revision_number,
    update_working_revision_file,
)
from ..word_report import generate_report
from .readiness import evaluate_report_readiness, readiness_error
from .workspace import build_workspace


def generate_revision(*, visit_id: str, created_by: str) -> dict[str, Any]:
    """Generate a real DOCX from one frozen visit workspace and store its revision record."""
    workspace = build_workspace(visit_id)
    if workspace is None:
        raise ValueError("未找到要生成报告的访视")
    revisions = list_revisions(visit_id)
    latest_revision = next(iter(revisions), None)
    if latest_revision and latest_revision["status"] in {"submitted", "approved"}:
        raise ValueError("当前报告已提交审核或已批准，不能重新生成；请等待 PM/LM 退回后再创建修订版本")
    readiness = evaluate_report_readiness(visit_id)
    if not readiness["ready"]:
        raise ValueError(readiness_error(readiness))

    draft_shell = next(
        (
            revision
            for revision in revisions
            if revision.get("revision_type") == "working"
            and revision.get("status") == "draft"
            and not str(revision.get("file_path") or "").strip()
        ),
        None,
    )
    version_number = str(draft_shell["version_number"]) if draft_shell else next_revision_number(visit_id)
    output_path = generate_report(workspace, revision_number=version_number)
    file_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    if draft_shell:
        revision = update_working_revision_file(
            revision_id=draft_shell["id"],
            file_name=output_path.name,
            file_path=str(output_path),
            file_hash=file_hash,
        )
    else:
        parent_revision_id = latest_revision["id"] if latest_revision and latest_revision.get("status") in {"returned", "withdrawn"} else None
        revision = create_report_revision(
            visit_id,
            version_number=version_number,
            file_name=output_path.name,
            file_path=str(output_path),
            file_hash=file_hash,
            parent_revision_id=parent_revision_id,
        )
    create_audit_event(
        project_id=workspace["visit"]["project_id"],
        visit_id=visit_id,
        entity_type="report_revision",
        entity_id=revision["id"],
        action="generated",
        actor_name=created_by,
        detail={
            "version_number": version_number,
            "file_name": output_path.name,
            "file_hash": file_hash,
            "readiness": readiness["summary"],
            "parent_revision_id": revision.get("parent_revision_id") or "",
            "reused_working_draft": bool(draft_shell),
        },
    )
    return revision
