# PRD V0.3 Static Coverage Audit — 2026-08-12

## Scope and evidence

This is a source-level audit only. It does not replace browser, API, DOCX, or regression acceptance, which remains deferred by the workspace implementation-first rule.

Primary evidence reviewed:

- `backend/database.py`
- `backend/services/monitoring.py`
- `backend/services/clarifications.py`
- `backend/services/continuity.py`
- `backend/services/reports.py`
- `backend/services/project_eligibility.py`
- `backend/repositories/visits.py`
- `frontend/src/components/ActionItemsPanel.tsx`
- `frontend/src/components/ProjectEligibilityPanel.tsx`
- `frontend/src/components/CollaborationPage.tsx`
- `frontend/src/components/ReportPage.tsx`
- `frontend/src/components/ReviewPage.tsx`
- PRD V0.3 sections FR-01 through FR-12 and business-rule table BR-01 through BR-30.

## Confirmed local MVP paths

| PRD area | Static evidence |
| --- | --- |
| FR-01 template upload, mapping, configuration approval and frozen visit template | Template services, template slots, template switching, and configuration approval flows are present. |
| FR-02 controlled project/site data, versioned documents, subject-code ledger, import preview and frozen snapshots | Controlled-data repositories, import batches, versioned project eligibility assessments, visit snapshots, selective master-data refresh/rollback, reassessment flow, and subject validation are present. |
| FR-03 IMV task creation, project eligibility snapshot, system/device checks and historical action follow-up | Visit creation copies the approved eligibility conclusion effective on the monitoring activity end date; task generation, `system_checks`, and `create_historical_action_follow_up` are present. |
| FR-04 fragmented record, correction, void, offline draft and attachment route | Work-record provenance, correction/void flow and offline-draft sync services are present. |
| FR-05 structured suggestions, evidence and CRA decision trace | Suggestion/confirmed-field provenance, `ai_executions`, subject validation and center-explanation separation are present. |
| FR-06 missing/conflict ledger and targeted resolution | Persistent clarification items/responses and deterministic rule/document/action conflicts are present. |
| FR-07 findings, actions, attachments, escalation receipt/disposition and historical follow-up | Action lifecycle, evidence attachments, escalation state and historical follow-up are present. |
| FR-08 controlled language suggestions | Language-suggestion generation, diff data, CRA accept/edit/reject decision flow, and reasoned revocation back to the original confirmed text are present. |
| FR-09 real DOCX export, readiness and revision chain | Report services, frozen fields and real report revisions are present. |
| FR-10 CRA submission and pre-review withdrawal | CRA confirmation, submitted revision, withdrawal reason and related working revision are present. |
| FR-11 PM/LM review claim, targeted comments, CRA resolution, return and approval | Explicit review claim, comment records/resolutions, return revision and approval path are present. |
| FR-12 audit export and workspace investigation | Audit events, CSV export, archive package and expandable audit-detail timeline are present. |

## Verified correction: action-to-finding relationship

The PRD requires many-to-many action/finding support. The current source already provides it:

- `action_item_findings` is a dedicated link table with a unique action/finding pair.
- Create and edit flows accept `finding_ids` arrays.
- The Action Items UI supports multi-select creation and later link replacement.
- Action closure only changes action status. It does not automatically close linked findings.
- Audit events record link changes with before/after finding identifiers.

No additional implementation is required for this PRD item.

## Delivered local product path

### Project MVP / blinding eligibility assessment

The local MVP now carries a separate, versioned project-eligibility ledger rather than treating the ordinary project blind-mode configuration as an approval record:

1. A project administrator creates a draft containing the assessment period and explicit local-MVP boundary declarations.
2. The project administrator saves, submits, or withdraws the pending version; rejected and withdrawn conclusions remain historical records, and a new assessment creates a new version.
3. QA / Clinical Operations may approve or return a submitted version with a recorded review note.
4. New visits select the highest approved version effective on the activity end date and copy the entire conclusion into `snapshot.project_eligibility`.
5. The portfolio page shows the current conclusion and version ledger, while the visit overview shows the frozen conclusion that actually governed that visit.

This wave intentionally does **not** reject visit creation when the assessment is missing or out of the local MVP boundary. That eligibility gate, browser/API/DOCX acceptance and regression work remain deferred until interaction confirmation.

### Cancellation of an unsubmitted visit draft

The report-state table says a draft may be deleted. The codebase now provides a visit-level draft cancellation endpoint and CRA portfolio UI.

The local clinical-workflow behavior is **cancel, do not physically delete**:

1. Only a draft/returned visit without a submitted formal revision can be cancelled.
2. CRA provides a reason.
3. The visit becomes `cancelled` and is read-only in the normal work queue.
4. Existing working notes and audit events remain retained; no historical DOCX is overwritten.
5. A cancelled visit is excluded from report generation and submission, but remains discoverable in the project ledger.

The delivered path records `visit/draft_cancelled` with actor, time, prior status, reason and formal-revision count. Browser/API/DOCX acceptance remains deferred until interaction confirmation.

## Delivered PRD 8.3 selective-reference path

The initial master-data refresh flow could preview and adopt all current-effective data but did not provide the PRD-required selective reference or undo operation. The local MVP now:

1. exposes one selection target per changed center profile or controlled-document type;
2. requires a CRA reason and applies only the CRA-selected targets to an editable visit snapshot;
3. stores exact pre/post snapshots, center-team values, and the adoption reason in `master_data_refreshes`;
4. lets CRA undo the latest effective adoption with a reason, while retaining an audit event; and
5. refuses to overwrite a snapshot that a later operation has already changed.

This is source-level evidence only. Browser/API/DOCX acceptance remains deferred until interaction confirmation.

## Delivered FR-08 language-revocation path

The controlled-language flow now preserves the full CRA decision lifecycle:

1. CRA may accept the proposal, adopt a manually edited display text, or reject it.
2. For an accepted or edited suggestion, CRA may enter a reason and revoke the adoption.
3. Revocation changes the suggestion to `revoked`, while retaining the prior `final_text`, decision actor and decision time.
4. The report/evidence resolver uses only `accepted` and `edited` suggestions, so the revoked field automatically displays its original CRA-confirmed text.
5. The local audit trail records `language_suggestion/revoked` with the prior decision, prior display text, linked confirmed field and revocation reason.

This is source-level evidence only. Browser/API/DOCX acceptance remains deferred until interaction confirmation.

## Items intentionally deferred until user confirms interaction

The workspace `AGENTS.md` requires proving the operational path first and postponing guardrails, compatibility protections, regression and acceptance testing until the user confirms the interaction.

- Approval must reject unresolved review comments.
- Server-side enforcement that submitter and approver are distinct users.
- Administrator-authorized CRA handover enforcement.
- Generation/submission/approval idempotency and field-hash mismatch blocking.
- WORM/hash-chain audit storage, break-glass workflow, SSO/MFA and external-model deployment controls.
- Local offline-draft encryption and sensitive-input/attachment screening.
- Eligibility blocking that requires an approved, in-boundary assessment before a new visit or report workflow can proceed.
- Browser, API, DOCX and regression acceptance across the newly completed waves.

These are not claimed complete by this audit.
