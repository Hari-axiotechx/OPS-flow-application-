"""
The React frontend was written against the old Google-Sheets backend and
reads records using the original spreadsheet column names, e.g.
`record['Record ID']`, `record.Status`, `record.ErrorMessage`. So we don't
change the frontend at all — we just make the new API return records
shaped exactly like the old one did.

NOTE: this file had accidentally been overwritten with a copy of logic.py
(which imports from this module -> circular import, backend could not
start). It has been restored from the compiled original and extended with
RollbackBranch, notifications and applications.
"""
from datetime import datetime


def _iso(dt) -> str:
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def user_public(u) -> dict | None:
    """Safe-to-send-to-the-browser view of a user (no password hash / OTP)."""
    if u is None:
        return None
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "mobile": u.mobile,
        "role": u.role,
        "requestedRole": u.requested_role,
        "power": bool(u.power),
        "active": bool(u.active),
        "status": u.status,
        "createdAt": _iso(u.created_at),
        "updatedAt": _iso(u.updated_at),
        "preferences": u.preferences or {},
    }


def user_admin_row(u) -> dict:
    """Row shown in the admin User Management table."""
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "mobile": u.mobile,
        "role": u.role,
        "requestedRole": u.requested_role,
        "power": bool(u.power),
        "active": bool(u.active),
        "status": u.status,
        "createdAt": _iso(u.created_at),
    }


def _audit_columns(r) -> dict:
    return {
        "CreatedBy": r.created_by,
        "CreatedAt": _iso(r.created_at),
        "UpdatedBy": r.updated_by,
        "UpdatedAt": _iso(r.updated_at),
    }


def deployment_record(d, with_file: bool = True) -> dict:
    return {
        "Record Type": "DEPLOYMENT",
        "Record ID": d.id,
        "Project": d.project,
        "Component": d.component,
        "Environment": d.environment,
        "DateTime": _iso(d.date_time),
        "GitHubURL": d.github_url or "",
        "GitHubBranch": d.github_branch or "",
        "GitHubCommit": d.github_commit or "",
        "RollbackBranch": d.rollback_branch or "",
        "DBChange": bool(d.db_change),
        "DBChangeDetails": d.db_change_details or "",
        "DBChangeFileName": d.db_change_file_name or "",
        # The uploaded file (base64) can be several MB. Lists / search / voice do not need it,
        # so it is only sent when ONE deployment is opened (with_file=True).
        "DBChangeFileData": (d.db_change_file_data or "") if with_file else "",
        "EnvVarChange": bool(d.env_var_change),
        "EnvVarDetails": d.env_var_details or "",
        "ThirdPartyAPIChange": bool(d.third_party_api_change),
        "ThirdPartyAPIDetails": d.third_party_api_details or "",
        "AdditionalInfo": d.additional_info or "",
        "ApplicationChangeDetails": getattr(d, "application_change_details", "") or "",
        # JSON string (files are big) -> only sent when ONE deployment is opened.
        "Attachments": (getattr(d, "attachments", "") or "") if with_file else "",
        "RequesterID": d.requester_id,
        "AssignedDevOpsID": d.assigned_devops_id or "",
        "Status": d.status,
        "RejectionReason": d.rejection_reason or "",
        "FailureReason": d.failure_reason or "",
        "RollbackReason": d.rollback_reason or "",
        "ResolvedBy": d.resolved_by or "",
        "ResolvedAt": _iso(d.resolved_at),
        **_audit_columns(d),
    }


def access_record(a) -> dict:
    return {
        "Record Type": "ACCESS",
        "Record ID": a.id,
        "AccessType": a.access_type,
        "Project": a.project,
        "Environment": a.environment,
        "UserResource": a.user_resource,
        "Permission": a.permission,
        "Reason": a.reason,
        "ExpiryDate": a.expiry_date or "",
        "RequesterID": a.requester_id,
        "Status": a.status,
        "RejectionReason": a.rejection_reason or "",
        "ResolvedBy": a.resolved_by or "",
        "ResolvedAt": _iso(a.resolved_at),
        **_audit_columns(a),
    }


def issue_record(i, record_type: str, with_file: bool = True) -> dict:
    rec = {
        "Record Type": record_type,
        "Record ID": i.id,
        "Project": i.project,
        "Environment": i.environment,
        "DateTime": _iso(i.date_time),
        "ErrorMessage": i.error_message,
        "Symptoms": i.symptoms or "",
        "Impact": i.impact or "",
        "Priority": i.priority,
        "Service": getattr(i, "service", "") or "",
        "LinkedDeploymentID": i.linked_deployment_id or "",
        "RequesterID": i.requester_id,
        "Status": i.status,
        "RootCause": i.root_cause or "",
        "WhatWasDone": i.what_was_done or "",
        "Resolution": i.resolution or "",
        "ResolvedBy": i.resolved_by or "",
        "ResolvedAt": _iso(i.resolved_at),
        **_audit_columns(i),
    }
    if record_type == "AWS_ISSUE":
        rec["ErrorFileName"] = getattr(i, "error_file_name", "") or ""
        rec["ImpactFileName"] = getattr(i, "impact_file_name", "") or ""
        # The file contents are big: only sent when ONE issue is opened (with_file=True).
        rec["ErrorFileData"] = (getattr(i, "error_file_data", "") or "") if with_file else ""
        rec["ImpactFileData"] = (getattr(i, "impact_file_data", "") or "") if with_file else ""
    return rec


def audit_entry(a) -> dict:
    return {
        "action": a.audit_action,
        "performedBy": a.performed_by,
        "at": _iso(a.created_at),
        "previousValue": a.previous_value or "",
        "newValue": a.new_value or "",
        "reason": a.reason or "",
    }


_SPOKEN_KIND = {
    "deployment": "Deployment update",
    "access": "Access request update",
    "aws": "AWS issue update",
    "user": "User update",
    "application": "Application update",
    "email": "Email alert",
}


def notification_speech(n) -> str:
    """Sentence the browser reads aloud when this notification arrives."""
    lead = _SPOKEN_KIND.get(n.kind or "info", "New notification")
    parts = [lead + ".", (n.title or "").strip().rstrip("."), (n.message or "").strip()]
    return " ".join(p if p.endswith((".", "!", "?")) else p + "." for p in parts if p)


def notification_record(n) -> dict:
    return {
        "id": n.id,
        "kind": n.kind or "info",
        "title": n.title,
        "message": n.message or "",
        "link": n.link or "",
        "recordId": n.record_id or "",
        "actor": n.actor or "",
        "read": bool(n.read),
        "createdAt": _iso(n.created_at),
        "speech": notification_speech(n),
    }


def application_record(a) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "date": a.launch_date or "",
        "createdBy": a.created_by or "",
        "createdAt": _iso(a.created_at),
    }