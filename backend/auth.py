"""Server-side identity resolution and role authorization (PRD V0.3 §13 permission matrix).

The demo previously trusted whatever free-text ``actor_name``/``reviewer_name`` string the
frontend sent in a request body, and exposed no server-side role check at all: "current role"
was a single shared UI toggle (see ``app_settings.current_role``), not an authenticated
identity. This module gives every request a resolved, trustworthy :class:`Actor` (a specific
``project_members`` row or a ``system_admins`` row) and a declarative route -> allowed-roles
map so that role/state-machine violations are rejected by the server, not just hidden by the
frontend, per PRD 8.4 ("服务端拒绝转换，不接受仅前端显示通过") and UAT-15.

This is still a local demo: there is no login/session/SSO layer (PRD 15.3 leaves that to the
customer's identity provider). The frontend picks an *identity* (a named project member or the
system administrator) instead of a bare role label, and sends it on every request via the
``X-Actor-Member-Id`` / ``X-Actor-System-Admin-Id`` headers. If neither header is present the
resolver falls back to the globally selected demo identity so older call sites keep working,
but flags the actor as ``implicit`` for audit purposes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from fastapi import HTTPException, Request
from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send

from .database import get_connection

MEMBER_ID_HEADER = "x-actor-member-id"
SYSTEM_ADMIN_ID_HEADER = "x-actor-system-admin-id"

SYSTEM_ADMIN_ROLE = "SYSTEM_ADMIN"
PROJECT_ROLES = {"CRA", "PM_LM", "PROJECT_ADMIN", "QA_CLINICAL_OPS", "MEDICAL_DATA_REVIEWER"}
ALL_ROLES = PROJECT_ROLES | {SYSTEM_ADMIN_ROLE}


@dataclass(frozen=True)
class Actor:
    member_id: str
    display_name: str
    role: str
    project_id: str | None
    is_system_admin: bool = False
    implicit: bool = False

    def as_audit_name(self) -> str:
        suffix = "（未显式登记身份，按当前演示身份推断）" if self.implicit else ""
        return f"{self.display_name}{suffix}"


class AuthError(HTTPException):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)


def _fetch_project_member(connection, member_id: str) -> Actor | None:
    row = connection.execute(
        "SELECT id, project_id, display_name, role, status FROM project_members WHERE id = ?",
        (member_id,),
    ).fetchone()
    if row is None or row["status"] != "active":
        return None
    return Actor(
        member_id=row["id"],
        display_name=row["display_name"],
        role=row["role"],
        project_id=row["project_id"],
        is_system_admin=False,
    )


def _fetch_system_admin(connection, admin_id: str) -> Actor | None:
    row = connection.execute(
        "SELECT id, display_name, status FROM system_admins WHERE id = ?",
        (admin_id,),
    ).fetchone()
    if row is None or row["status"] != "active":
        return None
    return Actor(
        member_id=row["id"],
        display_name=row["display_name"],
        role=SYSTEM_ADMIN_ROLE,
        project_id=None,
        is_system_admin=True,
    )


def _fallback_actor(connection) -> Actor | None:
    kind_row = connection.execute("SELECT value FROM app_settings WHERE key = 'current_actor_kind'").fetchone()
    member_row = connection.execute("SELECT value FROM app_settings WHERE key = 'current_member_id'").fetchone()
    kind = kind_row["value"] if kind_row else "project_member"
    identity_id = member_row["value"] if member_row else ""
    if not identity_id:
        return None
    if kind == "system_admin":
        actor = _fetch_system_admin(connection, identity_id)
    else:
        actor = _fetch_project_member(connection, identity_id)
    if actor is None:
        return None
    return Actor(
        member_id=actor.member_id,
        display_name=actor.display_name,
        role=actor.role,
        project_id=actor.project_id,
        is_system_admin=actor.is_system_admin,
        implicit=True,
    )


def resolve_actor(request: Request) -> Actor:
    """Resolve the trusted acting identity for a request from headers, or the demo fallback."""
    member_id = request.headers.get(MEMBER_ID_HEADER, "").strip()
    system_admin_id = request.headers.get(SYSTEM_ADMIN_ID_HEADER, "").strip()
    with get_connection() as connection:
        if system_admin_id:
            actor = _fetch_system_admin(connection, system_admin_id)
            if actor is None:
                raise AuthError(401, "未识别的系统管理员身份，请重新选择当前操作人")
            return actor
        if member_id:
            actor = _fetch_project_member(connection, member_id)
            if actor is None:
                raise AuthError(401, "未识别的项目成员身份，请重新选择当前操作人")
            return actor
        actor = _fallback_actor(connection)
        if actor is None:
            raise AuthError(401, "未提供操作人身份，且未配置默认演示身份")
        return actor


def get_actor(request: Request) -> Actor:
    """FastAPI dependency: return the already-resolved actor stashed on ``request.state``."""
    actor = getattr(request.state, "actor", None)
    if actor is None:
        actor = resolve_actor(request)
        request.state.actor = actor
    return actor


def require_roles(actor: Actor, roles: Iterable[str], *, action: str) -> None:
    allowed = set(roles)
    if actor.role not in allowed:
        raise AuthError(403, f"当前身份（{actor.role}）无权执行「{action}」，需要角色：{'/'.join(sorted(allowed))}")


def require_project_scope(actor: Actor, project_id: str, *, allow_system_admin_break_glass: bool = True) -> None:
    if actor.is_system_admin:
        if allow_system_admin_break_glass and _has_active_break_glass(project_id):
            return
        raise AuthError(403, "系统管理员默认无临床内容访问权限，且未查到该项目当前有效的破窗访问授权")
    if actor.project_id != project_id:
        raise AuthError(403, "当前身份不属于该项目，禁止跨项目访问")


def _has_active_break_glass(project_id: str) -> bool:
    from datetime import datetime

    with get_connection() as connection:
        rows = connection.execute(
            "SELECT expires_at FROM break_glass_requests WHERE project_id = ? AND status = 'active'",
            (project_id,),
        ).fetchall()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return any((row["expires_at"] or "") >= now for row in rows)


# ---------------------------------------------------------------------------
# Declarative route permission map (PRD §13 权限矩阵).
#
# Keys are (HTTP method, route path template exactly as declared with @app.*).
# A missing role set means "any resolved actor" (baseline authentication only,
# no fine-grained role restriction) — still rejects unresolvable/unknown
# identities, which is the minimum bar PRD UAT-15 asks for. Entries listed
# here enforce the specific role restrictions called out in the permission
# matrix and the FR sections for the highest-risk actions.
# ---------------------------------------------------------------------------

ROUTE_ROLES: dict[tuple[str, str], set[str]] = {
    # 项目 / 适用性评估
    ("POST", "/api/projects"): {"PROJECT_ADMIN", SYSTEM_ADMIN_ROLE},
    ("PATCH", "/api/projects/{project_id}"): {"PROJECT_ADMIN"},
    ("POST", "/api/projects/{project_id}/eligibility-assessments"): {"PROJECT_ADMIN"},
    ("PATCH", "/api/projects/{project_id}/eligibility-assessments/{assessment_id}"): {"PROJECT_ADMIN"},
    ("POST", "/api/projects/{project_id}/eligibility-assessments/{assessment_id}/approval"): {"QA_CLINICAL_OPS"},
    # 规则包
    ("POST", "/api/projects/{project_id}/rule-packs"): {"PROJECT_ADMIN"},
    ("PATCH", "/api/rule-packs/{rule_pack_id}"): {"PROJECT_ADMIN"},
    ("POST", "/api/rule-packs/{rule_pack_id}/approval-actions"): {"QA_CLINICAL_OPS"},
    # 项目成员
    ("POST", "/api/projects/{project_id}/members"): {"PROJECT_ADMIN"},
    ("PATCH", "/api/projects/{project_id}/members/{member_id}"): {"PROJECT_ADMIN"},
    # 模板
    ("POST", "/api/templates"): {"PROJECT_ADMIN"},
    ("POST", "/api/templates/{template_id}/revision-drafts"): {"PROJECT_ADMIN"},
    ("PUT", "/api/templates/{template_id}/document"): {"PROJECT_ADMIN"},
    ("POST", "/api/templates/{template_id}/configuration-package-imports"): {"PROJECT_ADMIN"},
    ("PATCH", "/api/templates/{template_id}/mappings/{mapping_id}"): {"PROJECT_ADMIN"},
    ("POST", "/api/templates/{template_id}/field-slots"): {"PROJECT_ADMIN"},
    ("POST", "/api/templates/{template_id}/field-slot-suggestion-imports"): {"PROJECT_ADMIN"},
    ("POST", "/api/templates/{template_id}/mapping-suggestion-imports"): {"PROJECT_ADMIN"},
    ("PATCH", "/api/templates/{template_id}/field-slots/{slot_id}"): {"PROJECT_ADMIN"},
    ("DELETE", "/api/templates/{template_id}/field-slots/{slot_id}"): {"PROJECT_ADMIN"},
    ("PATCH", "/api/templates/{template_id}/visit-type-keywords"): {"PROJECT_ADMIN"},
    ("PATCH", "/api/templates/{template_id}/completeness-rules"): {"PROJECT_ADMIN"},
    ("POST", "/api/templates/{template_id}/approval-actions"): {"PROJECT_ADMIN", "QA_CLINICAL_OPS"},
    # 中心 / 受控文件 / 主数据导入
    ("POST", "/api/sites"): {"PROJECT_ADMIN", "CRA"},
    ("PATCH", "/api/sites/{site_id}"): {"PROJECT_ADMIN", "CRA"},
    ("POST", "/api/sites/{site_id}/master-versions"): {"PROJECT_ADMIN", "CRA"},
    ("PATCH", "/api/site-master-versions/{version_id}"): {"PROJECT_ADMIN", "CRA"},
    ("POST", "/api/projects/{project_id}/controlled-documents"): {"PROJECT_ADMIN", "CRA"},
    ("PATCH", "/api/controlled-documents/{document_id}"): {"PROJECT_ADMIN", "CRA"},
    ("PUT", "/api/sites/{site_id}/subject-codes"): {"PROJECT_ADMIN", "CRA"},
    ("POST", "/api/imports/{scope}"): {"PROJECT_ADMIN", "CRA"},
    ("POST", "/api/imports/{scope}/preview"): {"PROJECT_ADMIN", "CRA"},
    ("POST", "/api/import-batches/{batch_id}/commit"): {"PROJECT_ADMIN", "CRA"},
    # 访视生命周期（CRA 独占的创建/编辑/记录/提交操作）
    ("POST", "/api/visits"): {"CRA"},
    ("PATCH", "/api/visits/{visit_id}"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/cancel"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/template-switch"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/template-switches/{switch_id}/rollback"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/date-reassess"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/master-data-refresh"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/master-data-refresh/rollback"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/clarifications/{item_id}/response"): {"CRA"},
    ("PATCH", "/api/visits/{visit_id}/tasks/{task_id}"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/tasks/bulk-update"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/records"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/records/{record_id}/corrections"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/records/{record_id}/void"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/offline-drafts/sync"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/sync-conflicts/{conflict_id}/resolve"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/escalations"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/escalations/{escalation_id}/disposition"): {"PM_LM"},
    ("POST", "/api/visits/{visit_id}/administrator-handovers"): {"PROJECT_ADMIN"},
    ("POST", "/api/visits/{visit_id}/handovers/{handover_id}/recipient-confirmation"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/suggestions/{suggestion_id}/decision"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/suggestions/{suggestion_id}/target-assignment"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/suggestions/batch-decision"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/language-suggestions/generate"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/language-suggestions/{suggestion_id}/decision"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/language-suggestions/{suggestion_id}/revoke"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/action-items"): {"CRA"},
    ("PATCH", "/api/visits/{visit_id}/action-items/{action_item_id}"): {"CRA"},
    ("PUT", "/api/visits/{visit_id}/action-items/{action_item_id}/findings"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/historical-actions/{source_action_item_id}/follow-up"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/attachments"): {"CRA"},
    ("POST", "/api/visits/{visit_id}/revisions/generate"): {"CRA"},
    ("POST", "/api/revisions/{revision_id}/submit"): {"CRA"},
    ("POST", "/api/revisions/{revision_id}/withdraw"): {"CRA"},
    ("POST", "/api/revisions/{revision_id}/void"): {"QA_CLINICAL_OPS"},
    ("POST", "/api/revisions/{revision_id}/review-start"): {"PM_LM"},
    ("POST", "/api/revisions/{revision_id}/reviews"): {"PM_LM"},
    ("POST", "/api/revisions/{revision_id}/specialist-comments"): {"PM_LM", "MEDICAL_DATA_REVIEWER"},
    ("POST", "/api/visits/{visit_id}/review-comments/{comment_id}/resolve"): {"CRA"},
    # 破窗访问
    ("POST", "/api/break-glass-requests"): {"CRA", "PM_LM", "PROJECT_ADMIN", "QA_CLINICAL_OPS", SYSTEM_ADMIN_ROLE},
    ("POST", "/api/break-glass-requests/{request_id}/business-approval"): {"PROJECT_ADMIN", "QA_CLINICAL_OPS"},
    ("POST", "/api/break-glass-requests/{request_id}/security-approval"): {SYSTEM_ADMIN_ROLE},
    ("POST", "/api/break-glass-requests/{request_id}/end"): {SYSTEM_ADMIN_ROLE, "PROJECT_ADMIN", "QA_CLINICAL_OPS"},
    ("POST", "/api/break-glass-requests/{request_id}/review"): {"QA_CLINICAL_OPS", SYSTEM_ADMIN_ROLE},
}

# Routes that never require identity resolution at all (demo utilities / health).
PUBLIC_ROUTES: set[tuple[str, str]] = {
    ("GET", "/api/health"),
    ("POST", "/api/reset"),
    ("GET", "/api/settings/current-role"),
    ("PUT", "/api/settings/current-role"),
    ("GET", "/api/identities"),
    ("GET", "/api/settings/current-identity"),
    ("PUT", "/api/settings/current-identity"),
}


class ActorAuthMiddleware:
    """ASGI middleware that resolves the acting identity and enforces ROUTE_ROLES.

    Implemented at the ASGI layer (rather than as a per-endpoint ``Depends``) so
    that role gating applies uniformly across the ~130 existing endpoints
    without having to touch every handler signature. It matches the incoming
    request against the FastAPI app's own compiled routes (the same matching
    FastAPI itself will use) to find the declared path template, so the
    ``ROUTE_ROLES``/``PUBLIC_ROUTES`` tables can be keyed on the readable
    ``@app.post("/api/...")`` strings.
    """

    def __init__(self, app: ASGIApp, fastapi_app: Any) -> None:
        self.app = app
        self.fastapi_app = fastapi_app

    def _match_route(self, scope: Scope) -> tuple[str, str] | None:
        for route in self.fastapi_app.router.routes:
            match, _child_scope = route.matches(scope)
            if match == Match.FULL:
                methods = getattr(route, "methods", None) or set()
                path = getattr(route, "path", None)
                if path is None:
                    continue
                method = scope.get("method", "GET")
                if method in methods:
                    return method, path
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        matched = self._match_route(scope)
        if matched is None or matched in PUBLIC_ROUTES:
            await self.app(scope, receive, send)
            return

        method, path_template = matched
        request = Request(scope, receive=receive)
        try:
            actor = resolve_actor(request)
            required_roles = ROUTE_ROLES.get(matched)
            if required_roles is not None:
                require_roles(actor, required_roles, action=f"{method} {path_template}")
        except AuthError as exc:
            await _write_denial(send, exc.status_code, str(exc.detail), path_template)
            _record_denied_access(path_template, method)
            return

        scope.setdefault("state", {})
        scope["state"]["actor"] = actor
        await self.app(scope, receive, send)


async def _write_denial(send: Send, status_code: int, detail: str, path: str) -> None:
    import json

    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _record_denied_access(path: str, method: str) -> None:
    from datetime import datetime
    from uuid import uuid4

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (id, project_id, visit_id, entity_type, entity_id, action, actor_name, detail_json, created_at)
                VALUES (?, '', '', 'access_control', ?, 'access_denied', 'unresolved_or_unauthorized', ?, ?)
                """,
                (
                    uuid4().hex,
                    path,
                    f'{{"method": "{method}", "path": "{path}"}}',
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                ),
            )
            connection.commit()
    except Exception:
        pass
