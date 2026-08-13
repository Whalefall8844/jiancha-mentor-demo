from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator
from uuid import uuid4


BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = BACKEND_DIR / "data"
DATABASE_PATH = DATA_DIR / "monitoring_mentor.db"
_INIT_LOCK = RLock()


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    sponsor TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sites (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    pi_name TEXT NOT NULL DEFAULT '',
    ethics_date TEXT NOT NULL DEFAULT '',
    protocol_version TEXT NOT NULL DEFAULT '',
    icf_version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, code)
);

CREATE TABLE IF NOT EXISTS site_master_versions (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    version_label TEXT NOT NULL,
    pi_name TEXT NOT NULL DEFAULT '',
    site_address TEXT NOT NULL DEFAULT '',
    site_team TEXT NOT NULL DEFAULT '',
    key_roles_json TEXT NOT NULL DEFAULT '{}',
    effective_from TEXT NOT NULL DEFAULT '',
    effective_to TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS controlled_documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    site_id TEXT REFERENCES sites(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,
    title TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    version_date TEXT NOT NULL DEFAULT '',
    effective_from TEXT NOT NULL DEFAULT '',
    effective_to TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    source_file_name TEXT NOT NULL DEFAULT '',
    stored_path TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    source_reference TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    docx_path TEXT NOT NULL,
    table_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    submitted_at TEXT NOT NULL DEFAULT '',
    submitted_by TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS template_mappings (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    table_index INTEGER NOT NULL,
    field_key TEXT NOT NULL,
    target_description TEXT NOT NULL DEFAULT '',
    required INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS template_field_slots (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    table_index INTEGER NOT NULL,
    target_kind TEXT NOT NULL DEFAULT 'table_cell',
    label TEXT NOT NULL DEFAULT '',
    field_key TEXT NOT NULL DEFAULT '',
    target_locator TEXT NOT NULL DEFAULT '',
    value_source TEXT NOT NULL DEFAULT 'confirmed_text',
    required INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rule_packs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    effective_from TEXT NOT NULL DEFAULT '',
    effective_to TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    submitted_at TEXT NOT NULL DEFAULT '',
    submitted_by TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, name, version)
);

CREATE TABLE IF NOT EXISTS project_members (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_eligibility_assessments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    assessment_version INTEGER NOT NULL,
    assessment_scope TEXT NOT NULL DEFAULT 'IMV_DOCX',
    blinding_mode TEXT NOT NULL DEFAULT 'open_label',
    processes_nonblind_data INTEGER NOT NULL DEFAULT 0,
    contains_direct_identifiers INTEGER NOT NULL DEFAULT 0,
    requires_full_blind_separation INTEGER NOT NULL DEFAULT 0,
    uses_editable_docx_only INTEGER NOT NULL DEFAULT 1,
    requires_ctms_etmf_integration INTEGER NOT NULL DEFAULT 0,
    assessment_note TEXT NOT NULL DEFAULT '',
    effective_from TEXT NOT NULL DEFAULT '',
    effective_to TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    submitted_at TEXT NOT NULL DEFAULT '',
    submitted_by TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    withdrawn_at TEXT NOT NULL DEFAULT '',
    withdrawn_by TEXT NOT NULL DEFAULT '',
    withdrawal_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, assessment_version)
);

CREATE TABLE IF NOT EXISTS visits (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL REFERENCES templates(id),
    rule_pack_id TEXT NOT NULL REFERENCES rule_packs(id),
    code TEXT NOT NULL,
    visit_type TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    activity_start_date TEXT NOT NULL DEFAULT '',
    visit_method TEXT NOT NULL DEFAULT '现场',
    visit_location TEXT NOT NULL DEFAULT '',
    contact_persons TEXT NOT NULL DEFAULT '',
    report_date TEXT NOT NULL,
    site_team TEXT NOT NULL DEFAULT '',
    monitoring_team TEXT NOT NULL DEFAULT '',
    next_visit TEXT NOT NULL DEFAULT '',
    cra_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(site_id, code)
);

CREATE TABLE IF NOT EXISTS visit_tasks (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    table_index INTEGER NOT NULL,
    task_type TEXT NOT NULL,
    field_key TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '待补录',
    evidence TEXT NOT NULL DEFAULT '',
    execution_date TEXT NOT NULL DEFAULT '',
    checked_scope TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    completed_by TEXT NOT NULL DEFAULT '',
    requires_evidence INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(visit_id, table_index)
);

CREATE TABLE IF NOT EXISTS subject_codes (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    enrollment_status TEXT NOT NULL DEFAULT 'screening',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(site_id, code)
);

CREATE TABLE IF NOT EXISTS work_records (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    record_kind TEXT NOT NULL DEFAULT 'monitoring_note',
    created_by TEXT NOT NULL,
    linked_task_id TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    client_idempotency_key TEXT NOT NULL DEFAULT '',
    corrected_record_id TEXT REFERENCES work_records(id),
    correction_reason TEXT NOT NULL DEFAULT '',
    record_status TEXT NOT NULL DEFAULT 'active',
    void_reason TEXT NOT NULL DEFAULT '',
    voided_at TEXT NOT NULL DEFAULT '',
    voided_by TEXT NOT NULL DEFAULT '',
    client_created_at TEXT NOT NULL DEFAULT '',
    client_timezone TEXT NOT NULL DEFAULT '',
    server_received_at TEXT NOT NULL DEFAULT '',
    text_hash TEXT NOT NULL DEFAULT '',
    processing_status TEXT NOT NULL DEFAULT 'completed',
    processing_error TEXT NOT NULL DEFAULT '',
    processed_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_executions (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    source_record_id TEXT NOT NULL REFERENCES work_records(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    schema_version TEXT NOT NULL DEFAULT '',
    rule_pack_version TEXT NOT NULL DEFAULT '',
    executed_at TEXT NOT NULL,
    input_record_hash TEXT NOT NULL DEFAULT '',
    output_hash TEXT NOT NULL DEFAULT '',
    validation_status TEXT NOT NULL DEFAULT 'valid',
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestions (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    source_record_id TEXT NOT NULL REFERENCES work_records(id) ON DELETE CASCADE,
    target_task_id TEXT REFERENCES visit_tasks(id),
    target_table INTEGER NOT NULL,
    field_key TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    proposed_text TEXT NOT NULL,
    source_text TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'narrative',
    assertion_type TEXT NOT NULL DEFAULT 'reported_observation',
    source_type TEXT NOT NULL DEFAULT 'work_record',
    evidence_text TEXT NOT NULL DEFAULT '',
    evidence_start INTEGER NOT NULL DEFAULT 0,
    evidence_end INTEGER NOT NULL DEFAULT 0,
    entity_type TEXT NOT NULL DEFAULT 'visit',
    entity_id TEXT NOT NULL DEFAULT '',
    pending_reason TEXT NOT NULL DEFAULT '',
    ai_execution_id TEXT NOT NULL DEFAULT '',
    subject_code TEXT NOT NULL DEFAULT '',
    subject_validation_status TEXT NOT NULL DEFAULT 'not_provided',
    subject_display_code TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending',
    final_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS confirmed_fields (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    suggestion_id TEXT REFERENCES suggestions(id),
    source_record_id TEXT REFERENCES work_records(id),
    target_table INTEGER NOT NULL,
    field_key TEXT NOT NULL,
    category TEXT NOT NULL,
    subject_code TEXT NOT NULL DEFAULT '',
    assertion_type TEXT NOT NULL DEFAULT 'reported_observation',
    source_type TEXT NOT NULL DEFAULT 'work_record',
    subject_validation_status TEXT NOT NULL DEFAULT 'not_provided',
    subject_display_code TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'accepted',
    decision_reason TEXT NOT NULL DEFAULT '',
    confirmed_by TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clarification_items (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    issue_key TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'high',
    is_blocking INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open',
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    target_task_id TEXT REFERENCES visit_tasks(id),
    target_table INTEGER NOT NULL DEFAULT 0,
    field_key TEXT NOT NULL DEFAULT '',
    candidates_json TEXT NOT NULL DEFAULT '[]',
    source_json TEXT NOT NULL DEFAULT '{}',
    resolution_json TEXT NOT NULL DEFAULT '{}',
    invalid_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT '',
    resolved_by TEXT NOT NULL DEFAULT '',
    UNIQUE(visit_id, issue_key)
);

CREATE TABLE IF NOT EXISTS clarification_responses (
    id TEXT PRIMARY KEY,
    clarification_item_id TEXT NOT NULL REFERENCES clarification_items(id) ON DELETE CASCADE,
    answer_text TEXT NOT NULL DEFAULT '',
    selected_candidate_id TEXT NOT NULL DEFAULT '',
    response_status TEXT NOT NULL,
    invalid_reason TEXT NOT NULL DEFAULT '',
    actor_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS template_switches (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    from_template_id TEXT NOT NULL REFERENCES templates(id),
    to_template_id TEXT NOT NULL REFERENCES templates(id),
    preview_json TEXT NOT NULL DEFAULT '{}',
    actor_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rolled_back_at TEXT NOT NULL DEFAULT '',
    rolled_back_by TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS visit_date_reassessments (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    from_visit_date TEXT NOT NULL,
    to_visit_date TEXT NOT NULL,
    from_rule_pack_id TEXT NOT NULL REFERENCES rule_packs(id),
    to_rule_pack_id TEXT NOT NULL REFERENCES rule_packs(id),
    preview_json TEXT NOT NULL DEFAULT '{}',
    actor_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS master_data_refreshes (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    selected_targets_json TEXT NOT NULL DEFAULT '[]',
    before_master_data_json TEXT NOT NULL DEFAULT '{}',
    after_master_data_json TEXT NOT NULL DEFAULT '{}',
    before_site_team TEXT NOT NULL DEFAULT '',
    after_site_team TEXT NOT NULL DEFAULT '',
    actor_name TEXT NOT NULL,
    adoption_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    rolled_back_at TEXT NOT NULL DEFAULT '',
    rolled_back_by TEXT NOT NULL DEFAULT '',
    rollback_reason TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS language_suggestions (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    confirmed_field_id TEXT NOT NULL REFERENCES confirmed_fields(id) ON DELETE CASCADE,
    rule_pack_id TEXT REFERENCES rule_packs(id),
    original_text TEXT NOT NULL,
    proposed_text TEXT NOT NULL,
    change_summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    final_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT '',
    revoked_at TEXT NOT NULL DEFAULT '',
    revoked_by TEXT NOT NULL DEFAULT '',
    revoke_reason TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    subject_code TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'open',
    source_suggestion_id TEXT REFERENCES suggestions(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_items (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    finding_id TEXT REFERENCES findings(id),
    source_action_item_id TEXT REFERENCES action_items(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    due_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    closure_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS action_item_findings (
    id TEXT PRIMARY KEY,
    action_item_id TEXT NOT NULL REFERENCES action_items(id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(action_item_id, finding_id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    action_item_id TEXT REFERENCES action_items(id),
    file_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_revisions (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    parent_revision_id TEXT REFERENCES report_revisions(id),
    version_number TEXT NOT NULL,
    revision_type TEXT NOT NULL DEFAULT 'working',
    status TEXT NOT NULL DEFAULT 'draft',
    file_name TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    generated_at TEXT NOT NULL DEFAULT '',
    submitted_at TEXT NOT NULL DEFAULT '',
    submitted_by TEXT NOT NULL DEFAULT '',
    review_started_at TEXT NOT NULL DEFAULT '',
    review_started_by TEXT NOT NULL DEFAULT '',
    withdrawn_at TEXT NOT NULL DEFAULT '',
    withdrawn_by TEXT NOT NULL DEFAULT '',
    withdrawn_reason TEXT NOT NULL DEFAULT '',
    voided_at TEXT NOT NULL DEFAULT '',
    voided_by TEXT NOT NULL DEFAULT '',
    void_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(visit_id, version_number)
);

CREATE TABLE IF NOT EXISTS review_comments (
    id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES report_revisions(id) ON DELETE CASCADE,
    target_key TEXT NOT NULL DEFAULT '',
    comment_type TEXT NOT NULL DEFAULT 'pm_lm_review',
    action TEXT NOT NULL,
    message TEXT NOT NULL,
    reviewer_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS review_comment_resolutions (
    id TEXT PRIMARY KEY,
    review_comment_id TEXT NOT NULL UNIQUE REFERENCES review_comments(id) ON DELETE CASCADE,
    resolution TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    resolved_by TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offline_drafts (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    base_updated_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_conflicts (
    id TEXT PRIMARY KEY,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    draft_id TEXT REFERENCES offline_drafts(id),
    field_key TEXT NOT NULL,
    local_value TEXT NOT NULL,
    server_value TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS operation_escalations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    action_item_id TEXT REFERENCES action_items(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'high',
    target_role TEXT NOT NULL DEFAULT 'PM_LM',
    sla_snapshot_json TEXT NOT NULL DEFAULT '{}',
    sla_due_at TEXT NOT NULL DEFAULT '',
    overdue_escalated_at TEXT NOT NULL DEFAULT '',
    overdue_escalated_to TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged_at TEXT NOT NULL DEFAULT '',
    acknowledged_by TEXT NOT NULL DEFAULT '',
    acknowledgement_note TEXT NOT NULL DEFAULT '',
    closed_at TEXT NOT NULL DEFAULT '',
    closed_by TEXT NOT NULL DEFAULT '',
    resolution_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS visit_handovers (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    from_member_id TEXT REFERENCES project_members(id),
    to_member_id TEXT NOT NULL REFERENCES project_members(id),
    note TEXT NOT NULL DEFAULT '',
    handover_mode TEXT NOT NULL DEFAULT 'cra_initiated',
    authorization_basis TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'completed',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged_at TEXT NOT NULL DEFAULT '',
    acknowledged_by TEXT NOT NULL DEFAULT '',
    acknowledgement_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    visit_id TEXT REFERENCES visits(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS configuration_audit_events (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    file_name TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    default_project_id TEXT NOT NULL DEFAULT '',
    default_site_id TEXT NOT NULL DEFAULT '',
    actor_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'previewed',
    preview_summary_json TEXT NOT NULL DEFAULT '{}',
    committed_summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    committed_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS import_batch_rows (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    action TEXT NOT NULL DEFAULT 'skip',
    entity_type TEXT NOT NULL DEFAULT '',
    operation_json TEXT NOT NULL DEFAULT '{}',
    source_row_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_admins (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    visit_id TEXT NOT NULL DEFAULT '',
    revision_id TEXT NOT NULL DEFAULT '',
    export_type TEXT NOT NULL,
    file_name TEXT NOT NULL DEFAULT '',
    file_hash TEXT NOT NULL DEFAULT '',
    report_version TEXT NOT NULL DEFAULT '',
    exported_by_member_id TEXT NOT NULL DEFAULT '',
    exported_by_name TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS break_glass_requests (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    object_scope TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    requested_by_role TEXT NOT NULL DEFAULT '',
    business_approver TEXT NOT NULL DEFAULT '',
    business_approved_at TEXT NOT NULL DEFAULT '',
    security_approver TEXT NOT NULL DEFAULT '',
    security_approved_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending_business_approval',
    emergency_self_activated INTEGER NOT NULL DEFAULT 0,
    max_duration_minutes INTEGER NOT NULL DEFAULT 60,
    activated_at TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL DEFAULT '',
    ended_at TEXT NOT NULL DEFAULT '',
    ended_reason TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT 'not_required',
    review_note TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_export_events_visit ON export_events(visit_id, created_at);
CREATE INDEX IF NOT EXISTS idx_break_glass_project_status ON break_glass_requests(project_id, status);

CREATE INDEX IF NOT EXISTS idx_sites_project ON sites(project_id);
CREATE INDEX IF NOT EXISTS idx_project_eligibility_project_status ON project_eligibility_assessments(project_id, status, assessment_version DESC);
CREATE INDEX IF NOT EXISTS idx_site_master_versions_site_effective ON site_master_versions(site_id, status, effective_from);
CREATE INDEX IF NOT EXISTS idx_controlled_documents_scope_effective ON controlled_documents(project_id, site_id, document_type, status, effective_from);
CREATE INDEX IF NOT EXISTS idx_visits_project_site ON visits(project_id, site_id);
CREATE INDEX IF NOT EXISTS idx_tasks_visit ON visit_tasks(visit_id);
CREATE INDEX IF NOT EXISTS idx_records_visit ON work_records(visit_id);
CREATE INDEX IF NOT EXISTS idx_suggestions_visit ON suggestions(visit_id);
CREATE INDEX IF NOT EXISTS idx_revisions_visit ON report_revisions(visit_id);
CREATE INDEX IF NOT EXISTS idx_language_suggestions_visit ON language_suggestions(visit_id, status);
CREATE INDEX IF NOT EXISTS idx_action_item_findings_action ON action_item_findings(action_item_id);
CREATE INDEX IF NOT EXISTS idx_action_item_findings_finding ON action_item_findings(finding_id);
CREATE INDEX IF NOT EXISTS idx_audit_project_visit ON audit_events(project_id, visit_id);
CREATE INDEX IF NOT EXISTS idx_escalations_visit_status ON operation_escalations(visit_id, status);
CREATE INDEX IF NOT EXISTS idx_handovers_visit ON visit_handovers(visit_id, created_at);
CREATE INDEX IF NOT EXISTS idx_configuration_audit_entity ON configuration_audit_events(entity_type, entity_id, created_at);
CREATE INDEX IF NOT EXISTS idx_import_batch_rows_batch ON import_batch_rows(batch_id, row_number);
CREATE INDEX IF NOT EXISTS idx_template_switches_visit ON template_switches(visit_id, created_at);
CREATE INDEX IF NOT EXISTS idx_visit_date_reassessments_visit ON visit_date_reassessments(visit_id, created_at);
CREATE INDEX IF NOT EXISTS idx_master_data_refreshes_visit ON master_data_refreshes(visit_id, created_at);
"""


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with _INIT_LOCK:
        with transaction() as connection:
            connection.executescript(SCHEMA)
            _ensure_visit_task_execution_columns(connection)
            _ensure_configuration_lifecycle_columns(connection)
            _ensure_action_item_relationship_columns(connection)
            _ensure_template_switch_columns(connection)
            _ensure_system_task_field_keys(connection)
            _ensure_visit_context_columns(connection)
            _ensure_template_field_slot_schema(connection)
            _ensure_import_batch_row_schema(connection)
            _ensure_work_record_metadata_schema(connection)
            _ensure_suggestion_evidence_schema(connection)
            _ensure_clarification_indexes(connection)
            _ensure_report_revision_workflow_columns(connection)
            _ensure_review_comment_type_column(connection)
            _ensure_operation_escalation_disposition_columns(connection)
            _ensure_operation_escalation_sla_columns(connection)
            _ensure_visit_handover_administration_columns(connection)
            _ensure_master_data_refresh_columns(connection)
            _ensure_language_suggestion_lifecycle_columns(connection)
            _ensure_report_revision_integrity_columns(connection)
            _ensure_attachment_security_columns(connection)
        from .seed_data import ensure_seed_data

        ensure_seed_data()


def _ensure_visit_task_execution_columns(connection: sqlite3.Connection) -> None:
    """Keep existing demo databases compatible with the additive task-evidence fields."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(visit_tasks)").fetchall()}
    additions = {
        "execution_date": "TEXT NOT NULL DEFAULT ''",
        "checked_scope": "TEXT NOT NULL DEFAULT ''",
        "rationale": "TEXT NOT NULL DEFAULT ''",
        "completed_by": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE visit_tasks ADD COLUMN {name} {definition}")


def _ensure_configuration_lifecycle_columns(connection: sqlite3.Connection) -> None:
    """Add approval metadata without changing existing active template/rule-pack records."""
    additions = {
        "submitted_at": "TEXT NOT NULL DEFAULT ''",
        "submitted_by": "TEXT NOT NULL DEFAULT ''",
        "reviewed_at": "TEXT NOT NULL DEFAULT ''",
        "reviewed_by": "TEXT NOT NULL DEFAULT ''",
        "review_note": "TEXT NOT NULL DEFAULT ''",
    }
    for table_name in ("templates", "rule_packs"):
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


def _ensure_action_item_relationship_columns(connection: sqlite3.Connection) -> None:
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(action_items)").fetchall()}
    if "source_action_item_id" not in existing:
        connection.execute("ALTER TABLE action_items ADD COLUMN source_action_item_id TEXT")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_action_items_source_action ON action_items(source_action_item_id)")


def _ensure_operation_escalation_disposition_columns(connection: sqlite3.Connection) -> None:
    """Add FR-07 receipt and disposition details to existing escalation rows."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(operation_escalations)").fetchall()}
    additions = {
        "acknowledged_by": "TEXT NOT NULL DEFAULT ''",
        "acknowledgement_note": "TEXT NOT NULL DEFAULT ''",
        "closed_at": "TEXT NOT NULL DEFAULT ''",
        "closed_by": "TEXT NOT NULL DEFAULT ''",
        "resolution_note": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE operation_escalations ADD COLUMN {name} {definition}")


def _ensure_operation_escalation_sla_columns(connection: sqlite3.Connection) -> None:
    """Persist each escalation's frozen rule-pack SLA without changing older rows."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(operation_escalations)").fetchall()}
    additions = {
        "sla_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
        "sla_due_at": "TEXT NOT NULL DEFAULT ''",
        "overdue_escalated_at": "TEXT NOT NULL DEFAULT ''",
        "overdue_escalated_to": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE operation_escalations ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_escalations_visit_sla_due "
        "ON operation_escalations(visit_id, status, sla_due_at)"
    )


def _ensure_visit_handover_administration_columns(connection: sqlite3.Connection) -> None:
    """Retain the administrator authorization and recipient confirmation for CRA handovers."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(visit_handovers)").fetchall()}
    additions = {
        "handover_mode": "TEXT NOT NULL DEFAULT 'cra_initiated'",
        "authorization_basis": "TEXT NOT NULL DEFAULT ''",
        "reason": "TEXT NOT NULL DEFAULT ''",
        "acknowledged_by": "TEXT NOT NULL DEFAULT ''",
        "acknowledgement_note": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE visit_handovers ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_handovers_visit_status "
        "ON visit_handovers(visit_id, status, created_at)"
    )


def _ensure_master_data_refresh_columns(connection: sqlite3.Connection) -> None:
    """Keep refresh-history rows able to retain the CRA's adoption reason."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(master_data_refreshes)").fetchall()}
    if "adoption_reason" not in existing:
        connection.execute("ALTER TABLE master_data_refreshes ADD COLUMN adoption_reason TEXT NOT NULL DEFAULT ''")


def _ensure_language_suggestion_lifecycle_columns(connection: sqlite3.Connection) -> None:
    """Keep historic language decisions while adding an explicit CRA revocation record."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(language_suggestions)").fetchall()}
    additions = {
        "revoked_at": "TEXT NOT NULL DEFAULT ''",
        "revoked_by": "TEXT NOT NULL DEFAULT ''",
        "revoke_reason": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE language_suggestions ADD COLUMN {name} {definition}")


def _ensure_template_switch_columns(connection: sqlite3.Connection) -> None:
    """Add active flags to existing visit data for reversible template migrations."""
    additions = {
        "visit_tasks": {"is_active": "INTEGER NOT NULL DEFAULT 1"},
        "suggestions": {
            "is_active": "INTEGER NOT NULL DEFAULT 1",
            "field_key": "TEXT NOT NULL DEFAULT ''",
        },
        "confirmed_fields": {"is_active": "INTEGER NOT NULL DEFAULT 1"},
    }
    for table_name, table_additions in additions.items():
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
        for name, definition in table_additions.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")
    task_fields = {row["name"] for row in connection.execute("PRAGMA table_info(visit_tasks)").fetchall()}
    if "field_key" not in task_fields:
        connection.execute("ALTER TABLE visit_tasks ADD COLUMN field_key TEXT NOT NULL DEFAULT ''")
    connection.execute("UPDATE visit_tasks SET field_key = 'table_' || table_index WHERE field_key = ''")
    connection.execute("UPDATE suggestions SET field_key = 'table_' || target_table WHERE field_key = ''")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_tasks_visit_active ON visit_tasks(visit_id, is_active, table_index)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_visit_active ON suggestions(visit_id, is_active)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_confirmed_fields_visit_active ON confirmed_fields(visit_id, is_active)")


def _ensure_system_task_field_keys(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT id, title, field_key FROM visit_tasks WHERE task_type = 'system_device_check'"
    ).fetchall()
    for row in rows:
        current_key = str(row["field_key"] or "").strip()
        if current_key and not current_key.startswith("table_"):
            continue
        field_key = f"system_check:{str(row['title'] or '').casefold().strip()}"
        connection.execute("UPDATE visit_tasks SET field_key = ? WHERE id = ?", (field_key, row["id"]))


def _ensure_visit_context_columns(connection: sqlite3.Connection) -> None:
    """Add FR-03 monitoring-activity context without disturbing existing visit records."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(visits)").fetchall()}
    additions = {
        "activity_start_date": "TEXT NOT NULL DEFAULT ''",
        "visit_method": "TEXT NOT NULL DEFAULT '现场'",
        "visit_location": "TEXT NOT NULL DEFAULT ''",
        "contact_persons": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE visits ADD COLUMN {name} {definition}")


def _ensure_template_field_slot_schema(connection: sqlite3.Connection) -> None:
    """Keep report-fill slots additive and independent from task-region mappings."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(template_field_slots)").fetchall()}
    additions = {
        "target_kind": "TEXT NOT NULL DEFAULT 'table_cell'",
        "label": "TEXT NOT NULL DEFAULT ''",
        "field_key": "TEXT NOT NULL DEFAULT ''",
        "target_locator": "TEXT NOT NULL DEFAULT ''",
        "value_source": "TEXT NOT NULL DEFAULT 'confirmed_text'",
        "required": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE template_field_slots ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_template_field_slots_template ON template_field_slots(template_id, table_index, created_at)"
    )


def _ensure_import_batch_row_schema(connection: sqlite3.Connection) -> None:
    """Keep source rows available for the administrator's import-error report."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(import_batch_rows)").fetchall()}
    if "source_row_json" not in existing:
        connection.execute("ALTER TABLE import_batch_rows ADD COLUMN source_row_json TEXT NOT NULL DEFAULT '{}'")


def _ensure_work_record_metadata_schema(connection: sqlite3.Connection) -> None:
    """Add PRD FR-04 context fields without rewriting historical work records."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(work_records)").fetchall()}
    additions = {
        "record_kind": "TEXT NOT NULL DEFAULT 'monitoring_note'",
        "linked_task_id": "TEXT NOT NULL DEFAULT ''",
        "recorded_at": "TEXT NOT NULL DEFAULT ''",
        "tags_json": "TEXT NOT NULL DEFAULT '[]'",
        "client_idempotency_key": "TEXT NOT NULL DEFAULT ''",
        "record_status": "TEXT NOT NULL DEFAULT 'active'",
        "void_reason": "TEXT NOT NULL DEFAULT ''",
        "voided_at": "TEXT NOT NULL DEFAULT ''",
        "voided_by": "TEXT NOT NULL DEFAULT ''",
        "client_created_at": "TEXT NOT NULL DEFAULT ''",
        "client_timezone": "TEXT NOT NULL DEFAULT ''",
        "server_received_at": "TEXT NOT NULL DEFAULT ''",
        "text_hash": "TEXT NOT NULL DEFAULT ''",
        "processing_status": "TEXT NOT NULL DEFAULT 'completed'",
        "processing_error": "TEXT NOT NULL DEFAULT ''",
        "processed_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE work_records ADD COLUMN {name} {definition}")
    connection.execute(
        "UPDATE work_records SET client_created_at = CASE WHEN recorded_at <> '' THEN recorded_at ELSE created_at END "
        "WHERE client_created_at = ''"
    )
    connection.execute("UPDATE work_records SET client_timezone = 'unknown' WHERE client_timezone = ''")
    connection.execute("UPDATE work_records SET record_kind = 'monitoring_note' WHERE record_kind = ''")
    connection.execute("UPDATE work_records SET server_received_at = created_at WHERE server_received_at = ''")
    connection.execute("UPDATE work_records SET processing_status = 'completed' WHERE processing_status = ''")
    connection.execute("UPDATE work_records SET processed_at = created_at WHERE processed_at = ''")
    for row in connection.execute("SELECT id, text FROM work_records WHERE text_hash = ''").fetchall():
        connection.execute(
            "UPDATE work_records SET text_hash = ? WHERE id = ?",
            (hashlib.sha256((row["text"] or "").encode("utf-8")).hexdigest(), row["id"]),
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_records_visit_idempotency "
        "ON work_records(visit_id, client_idempotency_key) WHERE client_idempotency_key <> ''"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_records_visit_status ON work_records(visit_id, record_status)")


def _ensure_suggestion_evidence_schema(connection: sqlite3.Connection) -> None:
    """Add evidence and execution fields without converting old suggestions into unqualified facts."""
    suggestion_columns = {row["name"] for row in connection.execute("PRAGMA table_info(suggestions)").fetchall()}
    suggestion_additions = {
        "value_type": "TEXT NOT NULL DEFAULT 'narrative'",
        "assertion_type": "TEXT NOT NULL DEFAULT 'reported_observation'",
        "source_type": "TEXT NOT NULL DEFAULT 'work_record'",
        "evidence_text": "TEXT NOT NULL DEFAULT ''",
        "evidence_start": "INTEGER NOT NULL DEFAULT 0",
        "evidence_end": "INTEGER NOT NULL DEFAULT 0",
        "entity_type": "TEXT NOT NULL DEFAULT 'visit'",
        "entity_id": "TEXT NOT NULL DEFAULT ''",
        "pending_reason": "TEXT NOT NULL DEFAULT ''",
        "ai_execution_id": "TEXT NOT NULL DEFAULT ''",
        "subject_validation_status": "TEXT NOT NULL DEFAULT 'not_provided'",
        "subject_display_code": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in suggestion_additions.items():
        if name not in suggestion_columns:
            connection.execute(f"ALTER TABLE suggestions ADD COLUMN {name} {definition}")

    confirmed_columns = {row["name"] for row in connection.execute("PRAGMA table_info(confirmed_fields)").fetchall()}
    confirmed_additions = {
        "decision": "TEXT NOT NULL DEFAULT 'accepted'",
        "decision_reason": "TEXT NOT NULL DEFAULT ''",
        "assertion_type": "TEXT NOT NULL DEFAULT 'reported_observation'",
        "source_type": "TEXT NOT NULL DEFAULT 'work_record'",
        "subject_validation_status": "TEXT NOT NULL DEFAULT 'not_provided'",
        "subject_display_code": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in confirmed_additions.items():
        if name not in confirmed_columns:
            connection.execute(f"ALTER TABLE confirmed_fields ADD COLUMN {name} {definition}")

    connection.execute("UPDATE suggestions SET value_type = 'narrative' WHERE value_type = ''")
    connection.execute("UPDATE suggestions SET assertion_type = 'reported_observation' WHERE assertion_type = ''")
    connection.execute("UPDATE suggestions SET source_type = 'work_record' WHERE source_type = ''")
    connection.execute("UPDATE suggestions SET evidence_text = source_text WHERE evidence_text = ''")
    connection.execute("UPDATE suggestions SET evidence_end = length(source_text) WHERE evidence_end = 0 AND source_text <> ''")
    connection.execute(
        "UPDATE suggestions SET entity_type = CASE WHEN subject_code <> '' AND subject_code <> '未提供受试者编号' THEN 'subject' ELSE 'visit' END "
        "WHERE entity_id = ''"
    )
    connection.execute(
        "UPDATE suggestions SET entity_id = CASE WHEN subject_code <> '' AND subject_code <> '未提供受试者编号' THEN subject_code ELSE visit_id END "
        "WHERE entity_id = ''"
    )
    connection.execute(
        "UPDATE suggestions SET pending_reason = CASE WHEN status = 'pending' THEN '需 CRA 对照原始记录确认' ELSE '历史建议未留存待确认原因' END "
        "WHERE pending_reason = ''"
    )
    connection.execute(
        "UPDATE suggestions SET subject_validation_status = CASE "
        "WHEN subject_code = '' OR subject_code = '未提供受试者编号' THEN 'not_provided' "
        "ELSE 'historical_unverified' END WHERE subject_validation_status = ''"
    )
    for row in connection.execute(
        "SELECT suggestion.id, suggestion.subject_code, project.metadata_json "
        "FROM suggestions suggestion "
        "JOIN visits visit ON visit.id = suggestion.visit_id "
        "JOIN projects project ON project.id = visit.project_id "
        "WHERE suggestion.subject_display_code = ''"
    ).fetchall():
        subject_code = str(row["subject_code"] or "")
        try:
            display_mode = json.loads(row["metadata_json"] or "{}").get("subject_code_display_mode", "masked")
        except json.JSONDecodeError:
            display_mode = "masked"
        connection.execute(
            "UPDATE suggestions SET subject_display_code = ? WHERE id = ?",
            (subject_code if display_mode == "full" else _mask_subject_code(subject_code), row["id"]),
        )
    connection.execute(
        "UPDATE confirmed_fields SET decision = COALESCE((SELECT status FROM suggestions WHERE suggestions.id = confirmed_fields.suggestion_id), 'accepted') "
        "WHERE decision = 'accepted' AND decision_reason = ''"
    )
    connection.execute(
        "UPDATE confirmed_fields SET assertion_type = COALESCE((SELECT assertion_type FROM suggestions WHERE suggestions.id = confirmed_fields.suggestion_id), 'reported_observation') "
        "WHERE assertion_type = 'reported_observation'"
    )
    connection.execute(
        "UPDATE confirmed_fields SET source_type = COALESCE((SELECT source_type FROM suggestions WHERE suggestions.id = confirmed_fields.suggestion_id), 'work_record') "
        "WHERE source_type = 'work_record'"
    )
    connection.execute(
        "UPDATE confirmed_fields SET subject_validation_status = COALESCE((SELECT subject_validation_status FROM suggestions WHERE suggestions.id = confirmed_fields.suggestion_id), 'not_provided') "
        "WHERE subject_validation_status = 'not_provided'"
    )
    connection.execute(
        "UPDATE confirmed_fields SET subject_display_code = COALESCE((SELECT subject_display_code FROM suggestions WHERE suggestions.id = confirmed_fields.suggestion_id), '') "
        "WHERE subject_display_code = ''"
    )
    for row in connection.execute("SELECT id, subject_code FROM confirmed_fields WHERE subject_display_code = ''").fetchall():
        connection.execute(
            "UPDATE confirmed_fields SET subject_display_code = ? WHERE id = ?",
            (_mask_subject_code(str(row["subject_code"] or "")), row["id"]),
        )

    historical_runs = connection.execute(
        """
        SELECT s.source_record_id, s.visit_id, MIN(s.created_at) AS executed_at,
               r.text_hash AS input_record_hash, COALESCE(rule_pack.version, '') AS rule_pack_version
        FROM suggestions s
        JOIN work_records r ON r.id = s.source_record_id
        JOIN visits v ON v.id = s.visit_id
        LEFT JOIN rule_packs rule_pack ON rule_pack.id = v.rule_pack_id
        WHERE s.ai_execution_id = ''
        GROUP BY s.source_record_id, s.visit_id, r.text_hash, rule_pack.version
        """
    ).fetchall()
    for run in historical_runs:
        output_rows = connection.execute(
            "SELECT id, field_key, category, proposed_text, source_text FROM suggestions WHERE source_record_id = ? AND ai_execution_id = '' ORDER BY created_at, rowid",
            (run["source_record_id"],),
        ).fetchall()
        output_payload = [dict(row) for row in output_rows]
        execution_id = uuid4().hex
        execution_time = run["executed_at"] or ""
        output_hash = hashlib.sha256(json.dumps(output_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        connection.execute(
            """
            INSERT INTO ai_executions (
                id, visit_id, source_record_id, provider, model_version, prompt_version, schema_version,
                rule_pack_version, executed_at, input_record_hash, output_hash, validation_status,
                retry_count, error_code, created_at
            ) VALUES (?, ?, ?, 'historical_untracked', 'unavailable', 'unavailable', 'unavailable', ?, ?, ?, ?, 'historical_untracked', 0, '', ?)
            """,
            (
                execution_id,
                run["visit_id"],
                run["source_record_id"],
                run["rule_pack_version"],
                execution_time,
                run["input_record_hash"],
                output_hash,
                execution_time,
            ),
        )
        connection.execute(
            "UPDATE suggestions SET ai_execution_id = ? WHERE source_record_id = ? AND ai_execution_id = ''",
            (execution_id, run["source_record_id"]),
        )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ai_executions_visit ON ai_executions(visit_id, executed_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_execution ON suggestions(ai_execution_id)")


def _ensure_clarification_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_clarification_items_visit_status "
        "ON clarification_items(visit_id, status, is_blocking, updated_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_clarification_responses_item "
        "ON clarification_responses(clarification_item_id, created_at)"
    )


def _ensure_report_revision_workflow_columns(connection: sqlite3.Connection) -> None:
    """Keep prior demo revisions usable while adding the FR-10/FR-11 version chain."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(report_revisions)").fetchall()}
    additions = {
        "parent_revision_id": "TEXT",
        "review_started_at": "TEXT NOT NULL DEFAULT ''",
        "review_started_by": "TEXT NOT NULL DEFAULT ''",
        "withdrawn_at": "TEXT NOT NULL DEFAULT ''",
        "withdrawn_by": "TEXT NOT NULL DEFAULT ''",
        "withdrawn_reason": "TEXT NOT NULL DEFAULT ''",
        "voided_at": "TEXT NOT NULL DEFAULT ''",
        "voided_by": "TEXT NOT NULL DEFAULT ''",
        "void_reason": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE report_revisions ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_report_revisions_parent ON report_revisions(parent_revision_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_report_revisions_review_lock ON report_revisions(visit_id, status, review_started_at)"
    )


def _ensure_review_comment_type_column(connection: sqlite3.Connection) -> None:
    """Distinguish PM/LM decisions from specialist collaboration notes."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(review_comments)").fetchall()}
    if "comment_type" not in existing:
        connection.execute("ALTER TABLE review_comments ADD COLUMN comment_type TEXT NOT NULL DEFAULT 'pm_lm_review'")
    connection.execute("UPDATE review_comments SET comment_type = 'pm_lm_review' WHERE comment_type = ''")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_comments_revision_type ON review_comments(revision_id, comment_type, created_at)"
    )


def _ensure_report_revision_integrity_columns(connection: sqlite3.Connection) -> None:
    """Add BR-17/BR-20/FR-09 identity, idempotency and file-integrity columns."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(report_revisions)").fetchall()}
    additions = {
        "file_hash": "TEXT NOT NULL DEFAULT ''",
        "confirmed_field_hash": "TEXT NOT NULL DEFAULT ''",
        "submitted_by_member_id": "TEXT NOT NULL DEFAULT ''",
        "review_started_by_member_id": "TEXT NOT NULL DEFAULT ''",
        "decided_by_member_id": "TEXT NOT NULL DEFAULT ''",
        "generation_idempotency_key": "TEXT NOT NULL DEFAULT ''",
        "submission_idempotency_key": "TEXT NOT NULL DEFAULT ''",
        "approval_idempotency_key": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE report_revisions ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_report_revisions_generation_key "
        "ON report_revisions(visit_id, generation_idempotency_key)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_report_revisions_submission_key "
        "ON report_revisions(submission_idempotency_key)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_report_revisions_approval_key "
        "ON report_revisions(approval_idempotency_key)"
    )


def _ensure_attachment_security_columns(connection: sqlite3.Connection) -> None:
    """Add BR-22/BR-23 hash, type/size and scan-status columns for uploaded attachments."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(attachments)").fetchall()}
    additions = {
        "file_hash": "TEXT NOT NULL DEFAULT ''",
        "content_type": "TEXT NOT NULL DEFAULT ''",
        "size_bytes": "INTEGER NOT NULL DEFAULT 0",
        "scan_status": "TEXT NOT NULL DEFAULT 'pending'",
        "scan_notes": "TEXT NOT NULL DEFAULT ''",
        "created_by_member_id": "TEXT NOT NULL DEFAULT ''",
        "deidentification_ack": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE attachments ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_attachments_visit_scan ON attachments(visit_id, scan_status)"
    )


def _mask_subject_code(value: str) -> str:
    subject_code = value.strip()
    if not subject_code or subject_code == "未提供受试者编号":
        return ""
    if "-" in subject_code or "_" in subject_code:
        prefix, _, _ = subject_code.replace("_", "-").rpartition("-")
        return f"{prefix}-***" if prefix else "***"
    if len(subject_code) <= 2:
        return "**"
    return f"{subject_code[:2]}{'*' * max(2, len(subject_code) - 2)}"


def reset_database() -> None:
    with _INIT_LOCK:
        with transaction() as connection:
            for table_name in (
                "audit_events",
                "export_events",
                "break_glass_requests",
                "clarification_responses",
                "clarification_items",
                "configuration_audit_events",
                "import_batch_rows",
                "import_batches",
                "visit_handovers",
                "operation_escalations",
                "sync_conflicts",
                "offline_drafts",
                "review_comment_resolutions",
                "review_comments",
                "report_revisions",
                "visit_date_reassessments",
                "template_switches",
                "attachments",
                "action_item_findings",
                "action_items",
                "findings",
                "language_suggestions",
                "confirmed_fields",
                "ai_executions",
                "suggestions",
                "work_records",
                "subject_codes",
                "visit_tasks",
                "visits",
                "project_members",
                "rule_packs",
                "template_field_slots",
                "template_mappings",
                "templates",
                "controlled_documents",
                "site_master_versions",
                "sites",
                "projects",
                "system_admins",
                "app_settings",
            ):
                connection.execute(f"DELETE FROM {table_name}")
        from .seed_data import ensure_seed_data

        ensure_seed_data()
