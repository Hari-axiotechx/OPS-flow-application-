"""
Every function here is a direct port of the matching handler in the old
Google Apps Script backend (backend/Code.gs in the original project).
Same validation, same status transitions, same audit trail — just
running against Postgres instead of a spreadsheet.
"""
from datetime import datetime, timezone
import json
import random
import re

from sqlalchemy import or_, String, Text
from sqlalchemy.orm import Session, defer

from .models import (
    User, Deployment, AccessRequest, Issue, AwsIssue, AuditLog, ConfigValue,
    Notification, Application,
)
from .auth_helpers import (
    Ctx, ROLES, require_auth, require_role, require_admin, is_admin,
    find_user_by_email, find_user_by_normalized_mobile, find_user_by_identifier,
    normalize_mobile,
)
from .security import hash_password, verify_password, make_session_token
from .ids import generate_id, generate_deployment_id
from .config import settings
from .errors import ApiError
from . import email_events
from .serializers import (
    user_public, user_admin_row, deployment_record, access_record, issue_record, audit_entry,
    notification_record, application_record,
)

DEFAULT_APPS = ["PG-Desk", "Stylo-Customer", "Stylo-Captain", "Axiokidz"]
DEFAULT_ENVS = ["DEV", "QA", "UAT", "PROD"]
DEFAULT_ACCESS_TYPES = ["RDS", "IAM", "IAM Permissions", "App Access", "Jenkins", "AWS Permissions", "Other"]
DEFAULT_PRIORITIES = ["Low", "Medium", "High", "Critical"]

DEPLOYMENT_TRANSITIONS = {
    "REQUESTED": ["APPROVED", "REJECTED"],
    "APPROVED": ["IN_PROGRESS"],
    "IN_PROGRESS": ["COMPLETED_SUCCESS", "COMPLETED_FAILED", "ROLLED_BACK"],
}
ACCESS_TRANSITIONS = {
    "REQUESTED": ["APPROVED", "REJECTED"],
    "APPROVED": ["IN_PROGRESS"],
    "IN_PROGRESS": ["ACCESS_GIVEN"],
}
LISTABLE_TYPES = ["DEPLOYMENT", "ACCESS", "ISSUE", "AWS_ISSUE"]
# The Issue Tracker module was removed from the UI, so it is no longer searched.
SEARCH_TYPES = ["DEPLOYMENT", "ACCESS", "AWS_ISSUE"]

# Common AWS services offered in the AWS Issue "Service" dropdown. The
# frontend also lets the user type any value that isn't in this list
# (a custom service), so this is a suggestion list, not a hard enum.
AWS_SERVICES = [
    "EC2", "S3", "RDS", "Lambda", "VPC", "IAM", "CloudFront", "Route 53",
    "ECS", "EKS", "DynamoDB", "CloudWatch", "SNS", "SQS", "API Gateway",
    "Elastic Beanstalk", "ELB / ALB", "EBS", "CloudFormation", "KMS",
    "Secrets Manager", "ElastiCache", "Redshift", "Kinesis",
    "Step Functions", "SES", "WAF", "ACM", "CodePipeline", "CodeBuild",
    "CodeDeploy", "Auto Scaling", "Elastic IP", "NAT Gateway", "EFS",
    "Athena", "Glue", "CloudTrail", "Systems Manager", "Other",
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value):
    """Best-effort parse of a datetime string (accepts the value coming
    straight out of an HTML <input type="datetime-local">, or a full ISO
    timestamp). Falls back to `now()` if it can't be parsed."""
    if isinstance(value, datetime):
        return value
    if not value:
        return now()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return now()


def is_past(dt: datetime) -> bool:
    """Safely check whether `dt` is already in the past.

    Values coming straight out of an HTML <input type="datetime-local">
    (e.g. "2026-09-26T14:09") have no timezone info at all, so `parse_dt`
    returns a naive `datetime`. Comparing a naive datetime directly against
    the timezone-aware `now()` above raises
    `TypeError: can't compare offset-naive and offset-aware datetimes` —
    which was silently turning every "createDeployment" call into an error
    response, no matter what date/time was picked. This picks the right
    "now" to compare against depending on whether `dt` is aware.
    """
    if dt.tzinfo is not None:
        return dt < now()
    return dt < datetime.now()


def log_audit(db: Session, related_id: str, action: str, performed_by: str,
               new_value: str = "", reason: str = "", previous_value: str = ""):
    record_id = generate_id(db, "AUDIT")
    db.add(AuditLog(
        id=record_id, audit_action=action, related_record_id=related_id,
        performed_by=performed_by, previous_value=previous_value or "",
        new_value=new_value or "", reason=reason or "", created_by=performed_by,
        created_at=now(), deleted=False,
    ))


def get_audit_trail(db: Session, record_id: str) -> list[dict]:
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.related_record_id == record_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    return [audit_entry(a) for a in rows]


# =====================================================================
# Notifications (bell icon, top-right of the header)
# =====================================================================

STATUS_LABELS = {
    "REQUESTED": "Requested", "APPROVED": "Approved", "REJECTED": "Rejected",
    "IN_PROGRESS": "In progress", "COMPLETED_SUCCESS": "Deployed successfully",
    "COMPLETED_FAILED": "Deployment failed", "ROLLED_BACK": "Rolled back",
    "ACCESS_GIVEN": "Access given", "OPEN": "Open", "RESOLVED": "Resolved",
}


def _label(status) -> str:
    return STATUS_LABELS.get(status, str(status or "").replace("_", " ").title())


def _active_user_ids(db: Session, role: str | None = None, admins_only: bool = False) -> list[str]:
    q = db.query(User).filter(User.active.is_(True), User.status == "APPROVED", User.deleted.is_(False))
    if role:
        q = q.filter(User.role == role)
    if admins_only:
        q = q.filter(User.role == "DevOps", User.power.is_(True))
    return [u.id for u in q.all()]


def notify(db: Session, recipient_ids, title: str, message: str = "", *, kind: str = "info",
           link: str = "", record_id: str = "", actor: User | None = None):
    """Create one notification per recipient. The person who performed the
    action never notifies themselves. Duplicate ids are collapsed."""
    seen = set()
    actor_id = actor.id if actor else None
    for rid in recipient_ids or []:
        if not rid or rid in seen or rid == actor_id:
            continue
        seen.add(rid)
        db.add(Notification(
            id=generate_id(db, "NOTIFICATION"), recipient_id=rid, kind=kind,
            title=title, message=message, link=link, record_id=record_id or None,
            actor=(actor.name if actor else "System"), read=False, created_at=now(),
        ))


def handle_list_notifications(db: Session, params: dict, ctx: Ctx) -> dict:
    user = require_auth(ctx)
    try:
        limit = max(1, min(int(params.get("limit") or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    base = db.query(Notification).filter(Notification.recipient_id == user.id)
    unread = base.filter(Notification.read.is_(False)).count()
    rows = base.order_by(Notification.read.asc(), Notification.created_at.desc()).limit(limit).all()
    return {"items": [notification_record(n) for n in rows], "unreadCount": unread}


def handle_mark_notification_read(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_auth(ctx)
    n = db.get(Notification, body.get("id"))
    if not n or n.recipient_id != user.id:
        raise ApiError("Notification not found.")
    n.read = True
    return {"id": n.id}


def handle_delete_notification(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_auth(ctx)
    n = db.get(Notification, body.get("id"))
    if not n or n.recipient_id != user.id:
        raise ApiError("Notification not found.")
    db.delete(n)
    return {"id": n.id}


def handle_mark_all_notifications_read(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_auth(ctx)
    updated = (
        db.query(Notification)
        .filter(Notification.recipient_id == user.id, Notification.read.is_(False))
        .update({Notification.read: True}, synchronize_session=False)
    )
    return {"updated": updated}


# ---------------------------------------------------------------------
# Generic record lookup across all four record types, by ID prefix
# (DEP-/ACC-/ISS-/AWS-), same trick the old backend used.
# ---------------------------------------------------------------------

_MODEL_BY_TYPE = {
    "DEPLOYMENT": Deployment,
    "ACCESS": AccessRequest,
    "ISSUE": Issue,
    "AWS_ISSUE": AwsIssue,
    "USER": User,
}


def find_record(db: Session, record_id: str):
    """Returns (obj, type) or (None, None)."""
    prefix = str(record_id).split("-")[0]
    prefix_to_type = {"DEP": "DEPLOYMENT", "ACC": "ACCESS", "ISS": "ISSUE",
                       "AWS": "AWS_ISSUE", "USR": "USER"}
    rtype = prefix_to_type.get(prefix)
    if not rtype:
        return None, None
    model = _MODEL_BY_TYPE[rtype]
    obj = db.get(model, record_id)
    return obj, rtype


def _to_dict(obj, rtype: str, full: bool = False) -> dict:
    """full=True is used only when a single record is opened (it includes the uploaded DB file)."""
    if rtype == "DEPLOYMENT":
        return deployment_record(obj, with_file=full)
    if rtype == "ACCESS":
        return access_record(obj)
    if rtype in ("ISSUE", "AWS_ISSUE"):
        return issue_record(obj, rtype, with_file=full)
    raise ApiError("Unsupported record type.")


def light_query(db: Session, model):
    """Query for lists / search: never loads the big base64 DB-change file column."""
    q = db.query(model)
    if model is Deployment:
        q = q.options(defer(Deployment.db_change_file_data), defer(Deployment.attachments))
    elif model is AwsIssue:
        q = q.options(defer(AwsIssue.error_file_data), defer(AwsIssue.impact_file_data))
    return q


def can_view_record(user: User, rtype: str) -> bool:
    if is_admin(user):
        return True
    if rtype == "AWS_ISSUE":
        return user.role == "DevOps"
    return True


def sees_all_records(user: User) -> bool:
    """DevOps engineers and the Admin see every deployment / access / AWS request.
    Developers and QA only see the requests they raised themselves."""
    return bool(user) and (user.role == "DevOps" or is_admin(user))


def can_view_item(user: User, rtype: str, obj) -> bool:
    """One specific record: allowed kind of record AND (sees everything OR raised by this user)."""
    if not can_view_record(user, rtype):
        return False
    return sees_all_records(user) or getattr(obj, "requester_id", None) == user.id


def active_devops_users(db: Session) -> list[dict]:
    rows = (
        db.query(User)
        .filter(User.role == "DevOps", User.active.is_(True), User.status == "APPROVED")
        .all()
    )
    return [user_public(u) for u in rows]


# =====================================================================
# Profile
# =====================================================================

def handle_update_profile(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_auth(ctx)

    name = str(body.get("name") or "").strip()
    preferences = body.get("preferences") if isinstance(body.get("preferences"), dict) else (user.preferences or {})

    if name:
        user.name = name

    if body.get("mobile") is not None:
        mobile = normalize_mobile(body.get("mobile"))
        if not (len(mobile) == 10 and mobile.isdigit()):
            raise ApiError("Enter a valid 10-digit mobile number.")
        duplicate = find_user_by_normalized_mobile(db, mobile, user.id)
        if duplicate:
            raise ApiError("That mobile number is already registered to another account.")
        old_mobile = user.mobile
        user.mobile = mobile
        if old_mobile != mobile:
            log_audit(db, user.id, "PROFILE_MOBILE_CHANGE", user.email, mobile, "", old_mobile or "")

    if body.get("newPassword"):
        if not body.get("currentPassword"):
            raise ApiError("Current password is required to set a new password.")
        if not verify_password(body["currentPassword"], user.password_hash):
            raise ApiError("Current password is incorrect.")
        _check_password_strength(body["newPassword"])
        if body["newPassword"] != body.get("confirmPassword"):
            raise ApiError("New passwords do not match.")
        user.password_hash = hash_password(body["newPassword"])
        log_audit(db, user.id, "PASSWORD_CHANGE", user.email, "Password updated")

    user.preferences = preferences
    user.updated_by = user.email
    user.updated_at = now()
    if body.get("preferences"):
        log_audit(db, user.id, "PREFERENCES_CHANGE", user.email, json.dumps(preferences))

    db.flush()
    return {"user": user_public(user)}


# =====================================================================
# Auth
# =====================================================================

PASSWORD_RULE_MSG = ("Password must be at least 8 characters and include 1 capital letter, "
                     "1 number and 1 special character.")


def _check_password_strength(password) -> None:
    p = str(password or "")
    if (len(p) < 8 or not re.search(r"[A-Z]", p) or not re.search(r"\d", p)
            or not re.search(r"[^A-Za-z0-9]", p)):
        raise ApiError(PASSWORD_RULE_MSG)


def handle_register(db: Session, body: dict) -> dict:
    name, email, password = body.get("name"), body.get("email"), body.get("password")
    mobile, role = body.get("mobile"), body.get("role")
    if not name or not email or not password:
        raise ApiError("Name, email and password are required.")
    allowed_domain = (settings.ALLOWED_EMAIL_DOMAIN or "").strip().lower()
    if allowed_domain and not email.strip().lower().endswith("@" + allowed_domain):
        raise ApiError(f"Only @{allowed_domain} email addresses can register.")
    if not mobile:
        raise ApiError("Mobile number is required.")
    normalized_mobile = normalize_mobile(mobile)
    if not re.fullmatch(r"[6-9]\d{9}", normalized_mobile):
        raise ApiError("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.")
    _check_password_strength(password)
    if not role or role not in ROLES:
        raise ApiError("Please select a valid role (Developer, QA or DevOps).")
    if find_user_by_email(db, email):
        raise ApiError("An account with this email already exists.")
    if find_user_by_normalized_mobile(db, normalized_mobile):
        raise ApiError("An account with this mobile number already exists.")

    record_id = generate_id(db, "USER")
    ts = now()
    db.add(User(
        id=record_id, name=name, email=email, mobile=normalized_mobile,
        password_hash=hash_password(password), role=None, requested_role=role,
        power=False, active=False, status="PENDING",
        created_by=email, created_at=ts, updated_by=email, updated_at=ts, deleted=False,
        preferences={},
    ))
    log_audit(db, record_id, "CREATED", email, role, "Registered, pending approval")
    notify(db, _active_user_ids(db, admins_only=True), "New user waiting for approval",
           f"{name} ({email}) registered as {role}.", kind="user", link="/users", record_id=record_id)
    db.flush()
    email_events.user_registered(db, db.get(User, record_id), role)
    return {"message": "Registration submitted. An admin will approve your account."}


def handle_admin_create_user(db: Session, body: dict, ctx: Ctx) -> dict:
    admin = require_admin(ctx)
    name = str(body.get("name") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    mobile = normalize_mobile(body.get("mobile"))
    password = body.get("password")
    role = body.get("role")
    power = role == "DevOps" and body.get("power") is True

    if not name or not email or not mobile or not isinstance(password, str) or not password:
        raise ApiError("Name, email, mobile number and password are required.")
    if len(name) > 30:
        raise ApiError("Name must be 30 characters or fewer.")
    if len(email) > 254:
        raise ApiError("Email address must be 254 characters or fewer.")
    _check_password_strength(password)
    if len(password.encode("utf-8")) > 72:
        raise ApiError("Password must be 72 bytes or fewer.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ApiError("Enter a valid email address.")
    allowed_domain = (settings.ALLOWED_EMAIL_DOMAIN or "").strip().lower()
    if allowed_domain and not email.endswith("@" + allowed_domain):
        raise ApiError(f"Only @{allowed_domain} email addresses can be added.")
    if not re.fullmatch(r"[6-9]\d{9}", mobile):
        raise ApiError("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.")
    if role not in ROLES:
        raise ApiError("Please select a valid role (Developer, QA or DevOps).")
    if find_user_by_email(db, email):
        raise ApiError("An account with this email already exists.")
    if db.query(User).filter(User.mobile == mobile).first():
        raise ApiError("An account with this mobile number already exists.")

    record_id = generate_id(db, "USER")
    ts = now()
    user = User(
        id=record_id, name=name, email=email, mobile=mobile,
        password_hash=hash_password(password), role=role, requested_role=None,
        power=power, active=True, status="APPROVED",
        created_by=admin.email, created_at=ts, updated_by=admin.email, updated_at=ts,
        deleted=False, preferences={},
    )
    db.add(user)
    db.flush()
    log_audit(db, record_id, "CREATED", admin.email, role,
              "Created by admin; active and approved" + (" with admin power" if power else ""))
    email_events.queue_admin_created_user_email(db, admin, user)
    return {"user": user_admin_row(user), "emailQueued": True}


def handle_login(db: Session, body: dict) -> dict:
    identifier = body.get("identifier") or body.get("email")
    password = body.get("password")
    user = find_user_by_identifier(db, identifier)
    if not user or not verify_password(password or "", user.password_hash):
        raise ApiError("Invalid email/mobile or password.")
    if user.status == "PENDING":
        raise ApiError("Your account is pending admin approval.")
    if user.status == "REJECTED":
        raise ApiError("Your registration was rejected. Contact an admin.")
    if not user.active:
        raise ApiError("Your account has been deactivated.")

    token = make_session_token(user.email)
    return {"token": token, "user": user_public(user)}


def handle_request_password_reset(db: Session, body: dict) -> dict:
    email = body.get("email")
    if not email:
        raise ApiError("Email is required.")
    user = find_user_by_email(db, email)
    # Don't reveal whether the email exists — respond the same way either way.
    if user:
        otp = f"{random.randint(100000, 999999)}"
        user.reset_otp = otp
        user.reset_otp_expiry = int((datetime.now().timestamp() + settings.OTP_TTL_MINUTES * 60) * 1000)
        email_events.queue_password_reset_email(db, user, otp)
    return {"message": "If that email is registered, a reset code has been sent to it."}


def handle_reset_password(db: Session, body: dict) -> dict:
    email, otp, new_password = body.get("email"), body.get("otp"), body.get("newPassword")
    if not email or not otp or not new_password:
        raise ApiError("Email, code and new password are all required.")
    user = find_user_by_email(db, email)
    if not user:
        raise ApiError("Invalid code. Please request a new one.")
    stored_otp = str(user.reset_otp or "")
    expiry = user.reset_otp_expiry or 0
    if not stored_otp or stored_otp != str(otp).strip():
        raise ApiError("Invalid code. Please check and try again.")
    if not expiry or datetime.now().timestamp() * 1000 > expiry:
        raise ApiError("This code has expired. Please request a new one.")
    _check_password_strength(new_password)

    user.password_hash = hash_password(new_password)
    user.reset_otp = None
    user.reset_otp_expiry = None
    user.updated_by = user.email
    user.updated_at = now()
    log_audit(db, user.id, "PASSWORD_RESET", user.email, "", "Reset via emailed OTP")
    return {"message": "Password updated. You can now sign in with your email or mobile number."}


# =====================================================================
# Bootstrap / config / listing / search
# =====================================================================

def handle_bootstrap(db: Session, ctx: Ctx) -> dict:
    user = require_auth(ctx)
    return {"user": user_public(user), "config": handle_get_config(db)}


def handle_get_config(db: Session) -> dict:
    rows = db.query(ConfigValue).filter(ConfigValue.deleted.is_(False)).all()
    by_key: dict[str, list[str]] = {}
    for r in rows:
        if r.config_value not in by_key.setdefault(r.config_key, []):
            by_key[r.config_key].append(r.config_value)
    applications = list(by_key.get("APPLICATION") or DEFAULT_APPS)
    for a in db.query(Application).order_by(Application.created_at.asc()).all():
        if a.name.lower() not in {x.lower() for x in applications}:
            applications.append(a.name)
    return {
        "applications": applications,
        "environments": by_key.get("ENVIRONMENT") or DEFAULT_ENVS,
        "accessTypes": by_key.get("ACCESS_TYPE") or DEFAULT_ACCESS_TYPES,
        "priorities": DEFAULT_PRIORITIES,
        "roles": ROLES,
    }


def handle_list_records(db: Session, params: dict, ctx: Ctx) -> list[dict]:
    user = require_auth(ctx)
    rtype = params.get("type")
    if rtype not in LISTABLE_TYPES:
        raise ApiError(f"Unknown record type: {rtype}")
    include_deleted = str(params.get("includeDeleted")) == "true"
    # Developer / QA always get only their own requests, whatever the browser asks for.
    mine_only = str(params.get("mineOnly")) == "true" or not sees_all_records(user)
    status = params.get("status")

    if not can_view_record(user, rtype):
        return []

    model = _MODEL_BY_TYPE[rtype]
    q = light_query(db, model)
    if not include_deleted and hasattr(model, "deleted"):
        q = q.filter(model.deleted.is_(False))
    if status:
        q = q.filter(model.status == status)
    if mine_only:
        q = q.filter(model.requester_id == user.id)
    rows = q.order_by(model.created_at.desc()).all()
    return [_to_dict(r, rtype) for r in rows]


def handle_get_record(db: Session, record_id: str, ctx: Ctx) -> dict:
    user = require_auth(ctx)
    obj, rtype = find_record(db, record_id)
    if not obj or getattr(obj, "deleted", False) or rtype not in LISTABLE_TYPES:
        raise ApiError("Record not found.")
    if not can_view_record(user, rtype):
        raise ApiError("Forbidden.")
    if not can_view_item(user, rtype, obj):
        raise ApiError("Record not found.")   # someone else's request: behaves as if it does not exist
    return {"record": _to_dict(obj, rtype, full=True), "audit": get_audit_trail(db, record_id)}


def handle_list_users(db: Session, ctx: Ctx) -> list[dict]:
    require_admin(ctx)
    rows = db.query(User).order_by(User.created_at.desc()).all()
    return [user_admin_row(u) for u in rows]


def handle_list_devops_users(db: Session, ctx: Ctx) -> list[dict]:
    require_auth(ctx)
    return active_devops_users(db)


def handle_list_email_recipients(db: Session, ctx: Ctx) -> list[dict]:
    """People that can be searched and picked in the To / Cc boxes of the request forms."""
    require_auth(ctx)
    return email_events.list_recipient_options(db)


def handle_send_test_email(db: Session, body: dict, ctx: Ctx) -> dict:
    """Admin only. Sends a real test e-mail RIGHT NOW (not in the background) and returns the
    mail server's real answer, so a broken SMTP / SES set-up can be diagnosed from the app."""
    from . import mailer
    user = require_admin(ctx)
    target = (body.get("to") or user.email or "").strip()
    if "@" not in target:
        raise ApiError("Enter a valid e-mail address.")
    if not mailer.settings.MAIL_ENABLED:
        raise ApiError("E-mail is switched off on the server: set MAIL_ENABLED=true in the .env file and restart the backend.")
    try:
        result = mailer.send_test(target)
    except mailer.MailError as e:
        raise ApiError(f"Test e-mail failed: {e}")
    except Exception as e:
        raise ApiError(f"Test e-mail failed: {mailer._short(e, 300)}")
    failed = result.get("failed") or {}
    if failed:
        raise ApiError("Not delivered: " + "; ".join(f"{a}: {w}" for a, w in failed.items()))
    return {"sentTo": target, "provider": mailer.settings.MAIL_PROVIDER}


def handle_search(db: Session, q: str, ctx: Ctx) -> list[dict]:
    user = require_auth(ctx)
    if not q or not q.strip():
        return []
    needle = q.strip()
    esc = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    results = []
    for rtype in SEARCH_TYPES:
        if not can_view_record(user, rtype):
            continue
        model = _MODEL_BY_TYPE[rtype]
        # The database does the matching (text columns only, never the big file column);
        # only the matching rows are loaded and turned into dicts.
        cols = [c for c in model.__table__.columns
                if isinstance(c.type, (String, Text))
                and c.name not in ("db_change_file_data", "error_file_data", "impact_file_data")]
        query = light_query(db, model)
        if hasattr(model, "deleted"):
            query = query.filter(model.deleted.is_(False))
        if not sees_all_records(user):
            query = query.filter(model.requester_id == user.id)
        query = query.filter(or_(*[c.ilike(f"%{esc}%", escape="\\") for c in cols]))
        for r in query.order_by(model.created_at.desc()).limit(30).all():
            if not can_view_item(user, rtype, r):
                continue
            results.append(_to_dict(r, rtype))
            if len(results) >= 30:
                return results
    return results


# =====================================================================
# Deployment Requests
# =====================================================================

def find_deployment_conflict(db: Session, project, environment, date_time_raw, exclude_id=None):
    if not project or not environment or not date_time_raw:
        return None
    target = parse_dt(date_time_raw)
    window_seconds = 4 * 60 * 60
    open_statuses = ["REQUESTED", "APPROVED", "IN_PROGRESS"]
    q = db.query(Deployment).filter(
        Deployment.project == project,
        Deployment.environment == environment,
        Deployment.status.in_(open_statuses),
    )
    if exclude_id:
        q = q.filter(Deployment.id != exclude_id)
    for d in q.all():
        if not d.date_time:
            continue
        delta = abs((d.date_time.replace(tzinfo=d.date_time.tzinfo or timezone.utc) -
                     target.replace(tzinfo=target.tzinfo or timezone.utc)).total_seconds())
        if delta <= window_seconds:
            return {
                "message": f"Another open deployment exists for {project} / {environment} around this time.",
                "conflictingId": d.id,
            }
    return None


def _require_fields(f: dict, required: list[tuple[str, str]]) -> None:
    """Raise ApiError naming the first mandatory field that is empty."""
    for key, label in required:
        value = f.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ApiError(f"{label} is required.")


def _email_choice(body: dict) -> bool:
    """Is an e-mail being sent for this request? If so, a To recipient must be picked.

    All e-mails are mandatory; legacy `sendEmail` flags are ignored.
    Raises before anything is saved, so nothing is created half-way.
    """
    if not email_events._ids(body.get("emailTo")):
        raise ApiError("Select at least one 'To' email recipient. The email notification is mandatory for this request.")
    return True


def _env_var_rows(raw) -> list:
    try:
        rows = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and str(r.get("key", "")).strip()]


MAX_WORDS_LONG = 500      # Application change details / Additional information
MAX_WORDS_API = 250       # Third party API details (text box)
MAX_DB_FILES = 10
MAX_ENV_FILES = 3
MAX_FILE_CHARS = 7_500_000   # ~5 MB file as a base64 data URL


def _word_count(text) -> int:
    return len(str(text or "").split())


def _check_words(text, limit: int, label: str) -> None:
    if _word_count(text) > limit:
        raise ApiError(f"{label} must be {limit} words or fewer (it has {_word_count(text)}).")


def _clean_file(f):
    if not isinstance(f, dict):
        return None
    name, data = str(f.get("name") or "").strip()[:255], str(f.get("data") or "")
    if not name or not data:
        return None
    if len(data) > MAX_FILE_CHARS:
        raise ApiError(f"File '{name}' is too large (max 5MB).")
    return {"name": name, "data": data}


def _clean_attachments(raw) -> dict:
    """Only known keys survive; files are {name, data(base64 data URL)}."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    db_files = [x for x in (_clean_file(f) for f in (raw.get("dbFiles") or [])) if x]
    if len(db_files) > MAX_DB_FILES:
        raise ApiError(f"You can upload at most {MAX_DB_FILES} DB / Schema change files.")
    if db_files:
        out["dbFiles"] = db_files
    tp_files = [x for x in (_clean_file(f) for f in (raw.get("thirdPartyFiles") or [])[:1]) if x]
    if tp_files:
        out["thirdPartyFiles"] = tp_files
    pairs = [{"key": str(p.get("key", "")).strip(), "value": str(p.get("value", ""))}
             for p in (raw.get("thirdPartyPairs") or []) if isinstance(p, dict) and str(p.get("key", "")).strip()]
    if pairs:
        out["thirdPartyPairs"] = pairs
    raw_env_files = raw.get("envFiles") or []
    if not isinstance(raw_env_files, list):
        raise ApiError("Environment variable files must be uploaded as a list.")
    env_files = [x for x in (_clean_file(f) for f in raw_env_files) if x]
    legacy_env_file = _clean_file(raw.get("envFile"))
    if legacy_env_file:
        if "envFiles" in raw:
            env_files.append(legacy_env_file)
        else:
            out["envFile"] = legacy_env_file
    if len(env_files) > MAX_ENV_FILES:
        raise ApiError(f"You can upload at most {MAX_ENV_FILES} environment variable files.")
    if env_files:
        out["envFiles"] = env_files
    for k in ("appChangeFile", "additionalFile"):
        one = _clean_file(raw.get(k))
        if one:
            out[k] = one
    return out


def handle_create_deployment(db: Session, body: dict, ctx: Ctx) -> dict:
    # Only Developers/QA are allowed to raise a deployment request. DevOps
    # (engineers and admins) act on requests but never create them.
    user = require_role(ctx, ["Developer", "QA"])
    f = body.get("fields") or {}
    _require_fields(f, [
        ("project", "Project / App"), ("component", "Frontend / Backend"),
        ("environment", "Environment"), ("dateTime", "Date & Time"),
        ("githubUrl", "GitHub Repository URL"), ("githubBranch", "GitHub Branch"),
    ])   # Rollback Branch is optional
    _check_words(f.get("applicationChangeDetails"), MAX_WORDS_LONG, "Application Change Details")
    _check_words(f.get("additionalInfo"), MAX_WORDS_LONG, "Additional Information")
    att = _clean_attachments(f.get("attachments"))
    if f.get("component") != "Backend":
        for k in ("dbFiles", "thirdPartyFiles", "thirdPartyPairs", "envFile", "envFiles"):
            att.pop(k, None)
    send_email = _email_choice(body)   # deployment e-mail is mandatory
    if f.get("component") == "Backend":
        if f.get("dbChange") and not ((f.get("dbChangeFileData") or "").strip() or att.get("dbFiles")):
            raise ApiError("DB / Schema change file is required.")
        if f.get("thirdPartyApiChange"):
            _check_words(f.get("thirdPartyApiDetails"), MAX_WORDS_API, "Third Party API text")
            if not ((f.get("thirdPartyApiDetails") or "").strip() or att.get("thirdPartyFiles") or att.get("thirdPartyPairs")):
                raise ApiError("Third Party API details are required (text, a file, or key & values).")
        if f.get("envVarChange"):
            rows = _env_var_rows(f.get("envVarDetails"))
            if not rows and not (att.get("envFile") or att.get("envFiles")):
                raise ApiError("Environment variables are required.")
            if any(not str(r.get("value", "")).strip() for r in rows):
                raise ApiError("Every environment variable needs a value.")
    record_id = generate_deployment_id(db, f.get("project"))   # per-application series
    ts = now()

    requested_dt = parse_dt(f.get("dateTime"))
    if is_past(requested_dt):
        raise ApiError("Deployment date & time cannot be in the past.")

    # Requesters (Developer/QA) never pick the DevOps assignee themselves —
    # that only happens later via reassignment. Any assignedDevOpsId sent
    # from the client on creation is ignored server-side.
    assigned_id = ""
    if assigned_id:
        devops = next((u for u in active_devops_users(db) if u["id"] == assigned_id), None)
        if not devops:
            raise ApiError("Selected DevOps user is not active or approved.")

    conflict = find_deployment_conflict(db, f.get("project"), f.get("environment"), f.get("dateTime"))

    dep = Deployment(
        id=record_id, project=f.get("project"), component=f.get("component"),
        environment=f.get("environment"), date_time=requested_dt,
        github_url=f.get("githubUrl") or "",
        github_branch=f.get("githubBranch") or "",
        github_commit=f.get("githubCommit") or "",
        rollback_branch=f.get("rollbackBranch") or "",
        db_change=bool(f.get("dbChange")),
        db_change_details=f.get("dbChangeDetails") or "",
        db_change_file_name=((f.get("dbChangeFileName") or "")
                             or ", ".join(x["name"] for x in att.get("dbFiles", [])))[:255],
        db_change_file_data=f.get("dbChangeFileData") or "",
        env_var_change=bool(f.get("envVarChange")),
        env_var_details=f.get("envVarDetails") or "",
        third_party_api_change=bool(f.get("thirdPartyApiChange")),
        third_party_api_details=f.get("thirdPartyApiDetails") or "",
        additional_info=f.get("additionalInfo") or "",
        application_change_details=f.get("applicationChangeDetails") or "",
        attachments=json.dumps(att) if att else "",
        requester_id=user.id, assigned_devops_id=assigned_id or None, status="REQUESTED",
        created_by=user.email, created_at=ts, updated_by=user.email, updated_at=ts,
    )
    db.add(dep)
    db.flush()
    log_audit(db, record_id, "CREATED", user.email, "REQUESTED")
    if assigned_id:
        log_audit(db, record_id, "ASSIGNED", user.email, assigned_id, "Assigned on creation")
    notify(db, _active_user_ids(db, role="DevOps"), "New deployment request",
           f"{user.name} requested {dep.project or 'a deployment'} → {dep.environment or ''} ({record_id}).",
           kind="deployment", link=f"/deployments/{record_id}", record_id=record_id, actor=user)
    mail_info = email_events.deployment_created(db, user, dep, f, send_email, conflict,
                                                body.get("emailTo"), body.get("emailCc"), mandatory=True)
    return {"record": deployment_record(dep), "conflict": conflict, "email": mail_info}


def handle_resubmit_deployment(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_role(ctx, ["Developer", "QA"])
    dep = db.get(Deployment, body.get("id"))
    if not dep:
        raise ApiError("Deployment not found.")
    if dep.requester_id != user.id:
        raise ApiError("Only the person who requested this deployment can edit it.")
    if dep.status != "REJECTED":
        raise ApiError("Only a rejected deployment can be edited and resubmitted.")
    send_email = _email_choice(body)
    fields = body.get("fields") or {}
    _require_fields(fields, [
        ("project", "Project / App"), ("component", "Frontend / Backend"),
        ("environment", "Environment"), ("dateTime", "Date & Time"),
        ("githubUrl", "GitHub Repository URL"), ("githubBranch", "GitHub Branch"),
    ])
    _check_words(fields.get("applicationChangeDetails"), MAX_WORDS_LONG, "Application Change Details")
    _check_words(fields.get("additionalInfo"), MAX_WORDS_LONG, "Additional Information")
    attachments = _clean_attachments(fields.get("attachments"))
    if fields.get("component") != "Backend":
        for key in ("dbFiles", "thirdPartyFiles", "thirdPartyPairs", "envFile", "envFiles"):
            attachments.pop(key, None)

    if fields.get("component") == "Backend":
        if fields.get("dbChange") and not ((fields.get("dbChangeFileData") or "").strip() or attachments.get("dbFiles")):
            raise ApiError("DB / Schema change file is required.")
        if fields.get("thirdPartyApiChange"):
            _check_words(fields.get("thirdPartyApiDetails"), MAX_WORDS_API, "Third Party API details")
            if not ((fields.get("thirdPartyApiDetails") or "").strip()
                    or attachments.get("thirdPartyFiles") or attachments.get("thirdPartyPairs")):
                raise ApiError("Third Party API details are required (text, a file, or key & values).")
        if fields.get("envVarChange"):
            rows = _env_var_rows(fields.get("envVarDetails"))
            if not rows and not (attachments.get("envFile") or attachments.get("envFiles")):
                raise ApiError("Environment variables are required.")
            if any(not str(row.get("value", "")).strip() for row in rows):
                raise ApiError("Every environment variable needs a value.")

    requested_dt = parse_dt(fields.get("dateTime"))
    if is_past(requested_dt):
        raise ApiError("Deployment date & time cannot be in the past.")

    conflict = find_deployment_conflict(
        db, fields.get("project"), fields.get("environment"), fields.get("dateTime")
    )
    previous = dep.status
    dep.project = fields.get("project")
    dep.component = fields.get("component")
    dep.environment = fields.get("environment")
    dep.date_time = requested_dt
    dep.github_url = fields.get("githubUrl") or ""
    dep.github_branch = fields.get("githubBranch") or ""
    dep.github_commit = fields.get("githubCommit") or ""
    dep.rollback_branch = fields.get("rollbackBranch") or ""
    dep.db_change = bool(fields.get("dbChange")) if dep.component == "Backend" else False
    dep.db_change_details = fields.get("dbChangeDetails") or "" if dep.component == "Backend" else ""
    dep.db_change_file_name = (
        (fields.get("dbChangeFileName") or "")
        or ", ".join(item["name"] for item in attachments.get("dbFiles", []))
    )[:255] if dep.component == "Backend" else ""
    dep.db_change_file_data = fields.get("dbChangeFileData") or "" if dep.component == "Backend" else ""
    dep.env_var_change = bool(fields.get("envVarChange")) if dep.component == "Backend" else False
    dep.env_var_details = fields.get("envVarDetails") or "" if dep.component == "Backend" else ""
    dep.third_party_api_change = bool(fields.get("thirdPartyApiChange")) if dep.component == "Backend" else False
    dep.third_party_api_details = fields.get("thirdPartyApiDetails") or "" if dep.component == "Backend" else ""
    dep.application_change_details = fields.get("applicationChangeDetails") or ""
    dep.additional_info = fields.get("additionalInfo") or ""
    dep.attachments = json.dumps(attachments) if attachments else ""
    dep.status = "REQUESTED"
    dep.rejection_reason = ""
    dep.failure_reason = ""
    dep.rollback_reason = ""
    dep.resolved_by = None
    dep.resolved_at = None
    dep.updated_by = user.email
    dep.updated_at = now()

    log_audit(db, dep.id, "RESUBMITTED", user.email, "REQUESTED", "", previous)
    notify(db, _active_user_ids(db, role="DevOps"), "Deployment request resubmitted",
           f"{user.name} resubmitted {dep.project or 'a deployment'} → {dep.environment or ''} ({dep.id}).",
           kind="deployment", link=f"/deployments/{dep.id}", record_id=dep.id, actor=user)
    mail_info = email_events.deployment_created(
        db, user, dep, fields, send_email, conflict, body.get("emailTo"), body.get("emailCc"),
        mandatory=True, resubmitted=True
    )
    return {"record": deployment_record(dep), "conflict": conflict, "email": mail_info}


def handle_update_deployment_status(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_role(ctx, ["DevOps"])
    record_id, new_status, reason = body.get("id"), body.get("newStatus"), body.get("reason")
    dep = db.get(Deployment, record_id)
    if not dep:
        raise ApiError("Deployment not found.")
    current = dep.status

    if new_status == "REJECTED" and not reason:
        raise ApiError("Rejection reason is mandatory.")
    if new_status == "REJECTED" and len(str(reason)) > 100:
        raise ApiError("Rejection reason must be 100 characters or fewer.")
    if new_status == "COMPLETED_FAILED" and not reason:
        raise ApiError("Failure reason is mandatory.")
    if new_status == "ROLLED_BACK" and not reason:
        raise ApiError("Rollback reason is mandatory.")

    allowed = DEPLOYMENT_TRANSITIONS.get(current, [])
    if new_status not in allowed and not is_admin(user):
        raise ApiError(f"Cannot move deployment from {current} to {new_status}.")

    # Status-change e-mails require at least one selected To recipient.
    # Checked before anything is saved, so nothing is changed half-way.
    outcome_mail = new_status in ("REJECTED", "COMPLETED_SUCCESS", "COMPLETED_FAILED", "ROLLED_BACK")
    if (outcome_mail and "emailTo" in body and body.get("sendEmail") is not False
            and not email_events._ids(body.get("emailTo"))):
        raise ApiError("Select at least one 'To' email recipient.")

    dep.status = new_status
    dep.updated_by = user.email
    dep.updated_at = now()
    if new_status == "REJECTED":
        dep.rejection_reason = reason
    if new_status == "COMPLETED_FAILED":
        dep.failure_reason = reason
    if new_status == "ROLLED_BACK":
        dep.rollback_reason = reason
    if new_status in ("COMPLETED_SUCCESS", "COMPLETED_FAILED", "ROLLED_BACK"):
        dep.resolved_by = user.email
        dep.resolved_at = now()

    log_audit(db, record_id, "STATUS_CHANGE", user.email, new_status, reason or "", current)
    msg = f"{record_id} ({dep.project or ''} / {dep.environment or ''}) is now {_label(new_status)}."
    if reason:
        msg += f" Reason: {reason}"
    notify(db, [dep.requester_id, dep.assigned_devops_id], f"Deployment {_label(new_status).lower()}",
           msg, kind="deployment", link=f"/deployments/{record_id}", record_id=record_id, actor=user)
    # Status-change email is queued and sent only after the transaction commits.
    email_events.deployment_outcome(db, user, dep, new_status, reason, body.get("sendEmail") is not False,
                                    body.get("emailTo"), body.get("emailCc"))
    return {"id": record_id, "newStatus": new_status}


def handle_reassign_deployment(db: Session, body: dict, ctx: Ctx) -> dict:
    # Assigning a deployment to a DevOps engineer is an Admin-only power.
    # A regular DevOps user (no `power` flag) is never allowed to assign —
    # not even to themselves or back to whoever had it before.
    user = require_admin(ctx)
    record_id, new_devops_id = body.get("id"), body.get("newDevOpsId")
    dep = db.get(Deployment, record_id)
    if not dep:
        raise ApiError("Deployment not found.")
    selected = next((u for u in active_devops_users(db) if u["id"] == new_devops_id), None)
    if not selected:
        raise ApiError("Selected DevOps user is not active or approved.")
    previous = dep.assigned_devops_id
    dep.assigned_devops_id = new_devops_id
    dep.updated_by = user.email
    dep.updated_at = now()
    log_audit(db, record_id, "REASSIGNED", user.email, new_devops_id, "", previous or "")
    notify(db, [new_devops_id], "Deployment assigned to you",
           f"Admin ({user.name}) assigned {record_id} ({dep.project or ''} / {dep.environment or ''}) to you.",
           kind="deployment", link=f"/deployments/{record_id}", record_id=record_id, actor=user)
    notify(db, [dep.requester_id], "Deployment reassigned",
           f"{record_id} was assigned to {selected['name']}.",
           kind="deployment", link=f"/deployments/{record_id}", record_id=record_id, actor=user)
    return {"id": record_id, "newDevOpsId": new_devops_id}


# Fields a DevOps user is allowed to edit on a deployment request, at any
# time and regardless of the current status — this is the "whoever can
# approve deployments can also fix up the schema / env / third-party API
# details on the request" permission. Maps the camelCase key the frontend
# sends to the ORM column name.
DEPLOYMENT_EDITABLE_FIELDS = {
    "rollbackBranch": "rollback_branch",
    "dbChange": "db_change",
    "dbChangeDetails": "db_change_details",
    "dbChangeFileName": "db_change_file_name",
    "dbChangeFileData": "db_change_file_data",
    "envVarChange": "env_var_change",
    "envVarDetails": "env_var_details",
    "thirdPartyApiChange": "third_party_api_change",
    "thirdPartyApiDetails": "third_party_api_details",
    "additionalInfo": "additional_info",
}


def handle_update_deployment(db: Session, body: dict, ctx: Ctx) -> dict:
    """Lets a DevOps user edit the schema/env-var/third-party-API details
    of a deployment request at any time — not just at creation, and not
    restricted to any single status. Only the fields present in `fields`
    are touched, so a partial edit never clobbers the rest of the record.
    Every changed field is written to the audit trail individually so the
    history stays inspectable."""
    user = require_role(ctx, ["DevOps"])
    record_id = body.get("id")
    fields = body.get("fields") or {}
    dep = db.get(Deployment, record_id)
    if not dep:
        raise ApiError("Deployment not found.")
    changed = []
    for key, column in DEPLOYMENT_EDITABLE_FIELDS.items():
        if key not in fields:
            continue
        is_flag = key.endswith("Change")
        new_value = bool(fields[key]) if is_flag else (fields[key] or "")
        old_value = getattr(dep, column)
        old_normalized = bool(old_value) if is_flag else (old_value or "")
        if old_normalized == new_value:
            continue
        setattr(dep, column, new_value)
        changed.append((key, old_value, new_value))

    if not changed:
        return {"record": deployment_record(dep)}

    dep.updated_by = user.email
    dep.updated_at = now()
    for key, old_value, new_value in changed:
        # File contents / long text are logged by field name only, not the
        # full payload, so the audit trail stays readable.
        if key in ("dbChangeFileData",):
            log_audit(db, record_id, "DETAILS_EDITED", user.email, "file updated", key)
        else:
            log_audit(db, record_id, "DETAILS_EDITED", user.email, str(new_value), key, str(old_value or ""))

    return {"record": deployment_record(dep)}


# =====================================================================
# Access Requests
# =====================================================================

def handle_create_access(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_role(ctx, ["Developer", "QA", "DevOps"])
    f = body.get("fields") or {}
    _require_fields(f, [
        ("accessType", "Access Type"), ("project", "Project / App"),
        ("environment", "Environment"), ("userResource", "User / Resource"),
        ("permission", "Access Level"), ("reason", "Reason"),
        ("expiryDate", "Expiry Date"),
    ])
    send_email = _email_choice(body)   # access e-mail is mandatory
    record_id = generate_id(db, "ACCESS")
    ts = now()
    acc = AccessRequest(
        id=record_id, access_type=f.get("accessType"), project=f.get("project"),
        environment=f.get("environment"), user_resource=f.get("userResource"),
        permission=f.get("permission"), reason=f.get("reason"), expiry_date=f.get("expiryDate") or "",
        requester_id=user.id, status="REQUESTED", created_by=user.email, created_at=ts,
        updated_by=user.email, updated_at=ts,
    )
    db.add(acc)
    db.flush()
    log_audit(db, record_id, "CREATED", user.email, "REQUESTED")
    notify(db, _active_user_ids(db, role="DevOps"), "New access request",
           f"{user.name} requested {acc.access_type or 'access'} on {acc.project or ''} / {acc.environment or ''} ({record_id}).",
           kind="access", link=f"/access/{record_id}", record_id=record_id, actor=user)
    mail_info = email_events.access_created(db, user, acc, send_email, body.get("emailTo"), body.get("emailCc"),
                                            mandatory=True)
    return {"record": access_record(acc), "email": mail_info}


def handle_update_access_status(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_role(ctx, ["DevOps"])
    record_id, new_status, reason = body.get("id"), body.get("newStatus"), body.get("reason")
    acc = db.get(AccessRequest, record_id)
    if not acc:
        raise ApiError("Access request not found.")
    current = acc.status

    if new_status == "REJECTED" and not reason:
        raise ApiError("Rejection reason is mandatory.")
    if new_status in ("ACCESS_GIVEN", "REJECTED") and "emailTo" in body and not email_events._ids(body.get("emailTo")):
        raise ApiError("Select at least one 'To' email recipient.")
    allowed = ACCESS_TRANSITIONS.get(current, [])
    if new_status not in allowed and not is_admin(user):
        raise ApiError(f"Cannot move access request from {current} to {new_status}.")

    acc.status = new_status
    acc.updated_by = user.email
    acc.updated_at = now()
    if new_status == "REJECTED":
        acc.rejection_reason = reason
    if new_status == "ACCESS_GIVEN":
        acc.resolved_by = user.email
        acc.resolved_at = now()

    log_audit(db, record_id, "STATUS_CHANGE", user.email, new_status, reason or "", current)
    msg = f"{record_id} ({acc.access_type or ''} · {acc.project or ''}) is now {_label(new_status)}."
    if reason:
        msg += f" Reason: {reason}"
    notify(db, [acc.requester_id], f"Access request {_label(new_status).lower()}", msg,
           kind="access", link=f"/access/{record_id}", record_id=record_id, actor=user)
    mail_info = email_events.access_status_changed(
        db, user, acc, new_status, reason, body.get("emailTo"), body.get("emailCc")
    )
    return {"id": record_id, "newStatus": new_status, "email": mail_info}


# =====================================================================
# Issue Tracker (DEV/QA/UAT — all three roles)
# =====================================================================

_ISSUE_FIELD_MAP = {
    "rootCause": "root_cause", "whatWasDone": "what_was_done", "resolution": "resolution",
    "symptoms": "symptoms", "impact": "impact", "priority": "priority",
}


def handle_create_issue(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_role(ctx, ["Developer", "QA", "DevOps"])
    f = body.get("fields") or {}
    if f.get("environment") == "PROD":
        raise ApiError("PROD issues must be filed as AWS Issues.")
    record_id = generate_id(db, "ISSUE")
    ts = now()
    issue = Issue(
        id=record_id, project=f.get("project"), environment=f.get("environment"),
        date_time=parse_dt(f.get("dateTime")) if f.get("dateTime") else ts,
        error_message=f.get("errorMessage"), symptoms=f.get("symptoms") or "",
        impact=f.get("impact") or "", priority=f.get("priority") or "Medium",
        linked_deployment_id=f.get("linkedDeploymentId") or None, requester_id=user.id,
        status="OPEN", created_by=user.email, created_at=ts, updated_by=user.email,
        updated_at=ts,
    )
    db.add(issue)
    db.flush()
    log_audit(db, record_id, "CREATED", user.email, "OPEN")
    return {"record": issue_record(issue, "ISSUE")}


def handle_update_issue(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_role(ctx, ["Developer", "QA", "DevOps"])
    record_id, fields, new_status = body.get("id"), body.get("fields"), body.get("newStatus")
    issue = db.get(Issue, record_id)
    if not issue:
        raise ApiError("Issue not found.")
    if issue.status == "RESOLVED" and not is_admin(user):
        raise ApiError("This issue is resolved and read-only.")

    if fields:
        for k, col in _ISSUE_FIELD_MAP.items():
            if k in fields and fields[k] is not None:
                setattr(issue, col, fields[k])

    previous = issue.status
    if new_status:
        issue.status = new_status
        if new_status == "RESOLVED":
            issue.resolved_by = user.email
            issue.resolved_at = now()
    issue.updated_by = user.email
    issue.updated_at = now()

    log_audit(db, record_id, "STATUS_CHANGE" if new_status else "UPDATED",
              user.email, new_status or "EDITED", "", previous)
    return {"id": record_id}


# =====================================================================
# AWS Issues (PROD only — DevOps only)
# =====================================================================

_AWS_ISSUE_FIELD_MAP = {
    "rootCause": "root_cause", "whatWasDone": "what_was_done", "resolution": "resolution",
    "symptoms": "symptoms", "impact": "impact", "priority": "priority", "service": "service",
    "errorMessage": "error_message", "project": "project",
}


MAX_ISSUE_WORDS = 500                 # Error / Message and Impact: 500 words each
MAX_ISSUE_FILE_CHARS = 7_200_000      # about 5 MB file once base64-encoded


def _check_issue_text_and_files(f: dict) -> None:
    for key, label in (("errorMessage", "Error / Message"), ("impact", "Impact")):
        if len(str(f.get(key) or "").split()) > MAX_ISSUE_WORDS:
            raise ApiError(f"{label} is over {MAX_ISSUE_WORDS} words. Shorten it, or upload a file for the rest.")
    for key, label in (("errorFileData", "Error / Message file"), ("impactFileData", "Impact file")):
        if len(str(f.get(key) or "")) > MAX_ISSUE_FILE_CHARS:
            raise ApiError(f"{label} is too large (maximum 5 MB).")


def handle_create_aws_issue(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_role(ctx, ["DevOps"])
    f = body.get("fields") or {}
    _require_fields(f, [
        ("project", "Project / App"), ("service", "Service"),
        ("errorMessage", "Error / Message"), ("impact", "Impact"),
    ])
    _check_issue_text_and_files(f)
    send_email = _email_choice(body)
    record_id = generate_id(db, "AWS_ISSUE")
    ts = now()
    issue = AwsIssue(
        id=record_id, project=f.get("project"), environment="PROD",
        date_time=parse_dt(f.get("dateTime")) if f.get("dateTime") else ts,
        error_message=f.get("errorMessage"), symptoms=f.get("symptoms") or "",
        impact=f.get("impact") or "", priority=f.get("priority") or "High",
        service=f.get("service") or None, requester_id=user.id,
        error_file_name=f.get("errorFileName") or "", error_file_data=f.get("errorFileData") or "",
        impact_file_name=f.get("impactFileName") or "", impact_file_data=f.get("impactFileData") or "",
        status="OPEN", created_by=user.email, created_at=ts, updated_by=user.email,
        updated_at=ts,
    )
    db.add(issue)
    db.flush()
    log_audit(db, record_id, "CREATED", user.email, "OPEN")
    notify(db, _active_user_ids(db, role="DevOps"), f"New AWS issue ({issue.priority})",
           f"{(issue.service + ' · ') if issue.service else ''}{issue.project or ''}: {(issue.error_message or '')[:140]}",
           kind="aws", link=f"/aws-issues/{record_id}", record_id=record_id, actor=user)
    mail_info = email_events.aws_issue_created(db, user, issue, send_email, body.get("emailTo"), body.get("emailCc"))
    return {"record": issue_record(issue, "AWS_ISSUE"), "email": mail_info}


def handle_update_aws_issue(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_role(ctx, ["DevOps"])
    record_id, fields, new_status = body.get("id"), body.get("fields"), body.get("newStatus")
    issue = db.get(AwsIssue, record_id)
    if not issue:
        raise ApiError("AWS issue not found.")
    if issue.status == "RESOLVED" and not is_admin(user):
        raise ApiError("This AWS issue is resolved and read-only.")

    if fields:
        for k, col in _AWS_ISSUE_FIELD_MAP.items():
            if k in fields and fields[k] is not None:
                setattr(issue, col, fields[k])

    previous = issue.status
    if new_status:
        issue.status = new_status
        if new_status == "RESOLVED":
            issue.resolved_by = user.email
            issue.resolved_at = now()
    issue.updated_by = user.email
    issue.updated_at = now()

    log_audit(db, record_id, "STATUS_CHANGE" if new_status else "UPDATED",
              user.email, new_status or "EDITED", "", previous)
    return {"id": record_id}


def handle_reopen_aws_issue(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_admin(ctx)
    record_id, reason = body.get("id"), body.get("reason")
    issue = db.get(AwsIssue, record_id)
    if not issue:
        raise ApiError("AWS issue not found.")
    if issue.status != "RESOLVED":
        raise ApiError("Only a resolved AWS issue can be reopened.")

    issue.status = "OPEN"
    issue.resolved_by = None
    issue.resolved_at = None
    issue.updated_by = user.email
    issue.updated_at = now()

    log_audit(db, record_id, "REOPENED", user.email, "OPEN", reason or "", "RESOLVED")
    notify(db, _active_user_ids(db, role="DevOps"), "AWS issue reopened",
           f"{issue.project or ''}: {(issue.error_message or '')[:140]}",
           kind="aws", link=f"/aws-issues/{record_id}", record_id=record_id, actor=user)
    return {"id": record_id}

# =====================================================================
# Applications (Admin only)
# =====================================================================

def _all_app_names(db: Session) -> list[str]:
    return handle_get_config(db)["applications"]


def handle_list_applications(db: Session, ctx: Ctx) -> list[dict]:
    """Default apps (shown as 'system' rows, can't be deleted) followed by
    the custom apps an admin added."""
    require_admin(ctx)
    custom = db.query(Application).order_by(Application.created_at.asc()).all()
    custom_names = {a.name.lower() for a in custom}
    rows = [
        {"id": "", "name": n, "date": "", "createdBy": "system", "createdAt": ""}
        for n in handle_get_config(db)["applications"] if n.lower() not in custom_names
    ]
    rows.extend(application_record(a) for a in custom)
    return rows


def handle_admin_add_application(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_admin(ctx)
    name = str(body.get("name") or "").strip()
    date = str(body.get("date") or "").strip()
    if not name:
        raise ApiError("Application name is required.")
    if not date:
        raise ApiError("Date is required.")
    if name.lower() in {n.lower() for n in _all_app_names(db)}:
        raise ApiError(f'"{name}" already exists.')

    ts = now()
    app_row = Application(
        id=generate_id(db, "APPLICATION"), name=name, launch_date=date,
        created_by=user.email, created_at=ts,
    )
    db.add(app_row)
    db.flush()
    log_audit(db, app_row.id, "CREATED", user.email, name, "Application added")
    notify(db, _active_user_ids(db), "New application added", f"{name} is now available in dropdowns.",
           kind="application", link="/applications", record_id=app_row.id, actor=user)
    return {"record": application_record(app_row), "config": handle_get_config(db)}


def handle_admin_remove_application(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_admin(ctx)
    name = str(body.get("name") or "").strip()
    app_row = db.query(Application).filter(Application.name == name).first()
    if not app_row:
        raise ApiError("Only applications added by an admin can be deleted.")
    app_id = app_row.id
    db.delete(app_row)      # real delete: the applications table has no 'deleted' column
    db.flush()
    log_audit(db, app_id, "DELETED", user.email, name, "Application removed")
    return {"config": handle_get_config(db)}


def handle_admin_add_config_value(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_admin(ctx)
    key = str(body.get("configKey") or "").strip()
    value = str(body.get("configValue") or "").strip()
    if key not in ("APPLICATION", "ENVIRONMENT", "ACCESS_TYPE"):
        raise ApiError("Unknown config key.")
    if not value:
        raise ApiError("Config value is required.")
    exists = db.query(ConfigValue).filter(
        ConfigValue.config_key == key, ConfigValue.deleted.is_(False)
    ).all()
    if value.lower() in {c.config_value.lower() for c in exists}:
        raise ApiError(f'"{value}" already exists.')
    db.add(ConfigValue(id=generate_id(db, "CONFIG"), config_key=key, config_value=value,
                       created_by=user.email, created_at=now(), deleted=False))
    db.flush()
    return {"config": handle_get_config(db)}


# =====================================================================
# User management (Admin only)
# =====================================================================

def _get_user(db: Session, user_id) -> User:
    u = db.get(User, user_id)
    if not u or u.deleted:
        raise ApiError("User not found.")
    return u


def handle_admin_approve_user(db: Session, body: dict, ctx: Ctx) -> dict:
    admin = require_admin(ctx)
    u = _get_user(db, body.get("id"))
    role = body.get("role")
    if role not in ROLES:
        raise ApiError("Please select a valid role (Developer, QA or DevOps).")
    u.role = role
    u.power = bool(body.get("power")) if role == "DevOps" else False
    u.active = True
    u.status = "APPROVED"
    u.updated_by, u.updated_at = admin.email, now()
    log_audit(db, u.id, "APPROVED", admin.email, role, "Power" if u.power else "")
    notify(db, [u.id], "Your account was approved", f"You can now sign in as {role}.",
           kind="user", actor=admin)
    return {"user": user_admin_row(u)}


def handle_admin_reject_user(db: Session, body: dict, ctx: Ctx) -> dict:
    admin = require_admin(ctx)
    u = _get_user(db, body.get("id"))
    u.status = "REJECTED"
    u.active = False
    u.role = None
    u.power = False
    u.updated_by, u.updated_at = admin.email, now()
    log_audit(db, u.id, "REJECTED", admin.email, "REJECTED", body.get("reason") or "")
    return {"user": user_admin_row(u)}


def handle_admin_update_user(db: Session, body: dict, ctx: Ctx) -> dict:
    admin = require_admin(ctx)
    u = _get_user(db, body.get("id"))
    role = body.get("role")
    if role not in ROLES:
        raise ApiError("Please select a valid role (Developer, QA or DevOps).")
    power = bool(body.get("power")) if role == "DevOps" else False
    if u.id == admin.id and (role != u.role or not power):
        raise ApiError("You cannot change your own role or admin power.")
    prev = f"{u.role}{' (Admin)' if u.power else ''}"
    was_power = bool(u.power)
    u.role, u.power = role, power
    u.updated_by, u.updated_at = admin.email, now()
    log_audit(db, u.id, "ROLE_CHANGE", admin.email, f"{role}{' (Admin)' if power else ''}", "", prev)
    if power and not was_power:
        notify(db, [u.id], "Admin access granted",
               f"{admin.name} gave you admin access. Refresh the page to see the admin menu.",
               kind="user", actor=admin)
    elif was_power and not power:
        notify(db, [u.id], "Admin access removed",
               f"{admin.name} removed your admin access. Refresh the page to update your menu.",
               kind="user", actor=admin)
    return {"user": user_admin_row(u)}


def handle_admin_deactivate_user(db: Session, body: dict, ctx: Ctx) -> dict:
    admin = require_admin(ctx)
    u = _get_user(db, body.get("id"))
    active = bool(body.get("active"))
    if u.id == admin.id and not active:
        raise ApiError("You cannot deactivate your own account.")
    u.active = active
    u.updated_by, u.updated_at = admin.email, now()
    log_audit(db, u.id, "ACTIVATED" if active else "DEACTIVATED", admin.email,
              "ACTIVE" if active else "INACTIVE")
    return {"user": user_admin_row(u)}


# =====================================================================
# Legacy soft delete (Admin only) — only models retaining soft-delete columns
# =====================================================================

def handle_soft_delete(db: Session, body: dict, ctx: Ctx) -> dict:
    user = require_admin(ctx)
    record_id = body.get("id")
    obj, rtype = find_record(db, record_id)
    if not obj or getattr(obj, "deleted", False) or rtype not in LISTABLE_TYPES:
        raise ApiError("Record not found.")
    if not hasattr(obj, "deleted"):
        raise ApiError("Deleting this record is not supported.")
    obj.deleted = True
    obj.deleted_by = user.email
    obj.deleted_at = now()
    log_audit(db, record_id, "DELETED", user.email, "DELETED")
    return {"id": record_id}