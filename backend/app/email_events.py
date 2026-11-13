"""
Which e-mails OPSFlow sends, to whom, and with what content.

  Deployment request  To / Cc: exactly the people picked in the form (search + select)
  Access request      To / Cc: exactly the people picked in the form (search + select)
  AWS (production) issue
                      To / Cc: exactly the people picked in the form (search + select)
  New registration    To: DevOps admins
  Deployment outcome  (deployed successfully / failed / rolled back)
                      To: requester + assigned DevOps + admin(s)   Cc: everyone else

Sender: always MAIL_FROM_ADDRESS (no-reply@axiotechx.com). The person who raised
the request is the Reply-To, so replies still reach a human.

All request and outcome e-mails ALWAYS send.
  * Legacy request flags and profile preferences cannot disable e-mail.
  * At least one "To" person must be picked for request forms. If the picked
    people cannot be resolved, mandatory requests go to DevOps admin(s).

Every function here is fail-safe: a problem building an e-mail is logged
and never breaks the request that triggered it.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from .config import settings
from .models import User
from .mailer import OutgoingEmail, queue_email
from .email_templates import Mail, Section, fmt_dt, render_html, render_text

log = logging.getLogger("opsflow.mail")

NAVY, TEAL, RED, SLATE = "#1e3a8a", "#0f766e", "#b91c1c", "#334155"
PRIORITY_COLOURS = {"Critical": "#b91c1c", "High": "#c2410c", "Medium": "#b45309", "Low": "#15803d"}
DEPLOYMENT_SKY, DEPLOYMENT_SKY_TEXT = "#e0f2fe", "#075985"
SUCCESS_BG, SUCCESS_TEXT = "#dcfce7", "#166534"
ROLLBACK_BG, ROLLBACK_TEXT = "#ffedd5", "#9a3412"
FAILURE_BG, FAILURE_TEXT = "#fee2e2", "#991b1b"
ACCESS_BG, ACCESS_TEXT = "#ecfccb", "#365314"


# ---------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------

def wants_email(user: User | None) -> bool:
    """E-mail notifications are always enabled for active users."""
    return bool(user)


def _users(db: Session, roles: list[str] | None = None, admins_only: bool = False,
           honour_opt_out: bool = True) -> list[User]:
    q = db.query(User).filter(User.active.is_(True), User.status == "APPROVED", User.deleted.is_(False))
    if admins_only:
        q = q.filter(User.role == "DevOps", User.power.is_(True))
    elif roles:
        q = q.filter(User.role.in_(roles))
    return [u for u in q.order_by(User.name).all() if u.email and (wants_email(u) or not honour_opt_out)]


def _pair(u: User) -> tuple[str, str]:
    return (u.name or "", u.email)


def _dedupe(users: list[User], taken: set[str]) -> list[tuple[str, str]]:
    out = []
    for u in users:
        key = u.email.lower()
        if key not in taken:
            taken.add(key)
            out.append(_pair(u))
    return out


def _ids(raw) -> list[str]:
    """Clean a list of user ids sent by the browser."""
    if not isinstance(raw, (list, tuple)):
        return []
    seen, out = set(), []
    for v in raw:
        v = str(v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def selected_recipients(db: Session, to_ids, cc_ids, mandatory: bool = False) -> tuple[list, list]:
    """To / Cc exactly as the person chose them in the form.

    * Only registered, active, approved OPSFlow users can be chosen (ids are
      looked up in the database, so a typed-in address can never be mailed).
    * User notification preferences do not suppress e-mails.
    * A person chosen in both boxes stays in To only.
    * mandatory=True: if nobody valid ends up in To, the DevOps admin(s) get it,
      so a mandatory e-mail is never silently dropped.
    """
    to_ids, cc_ids = _ids(to_ids), _ids(cc_ids)
    wanted = list(dict.fromkeys(to_ids + cc_ids))
    by_id = {u.id: u for u in _users(db, honour_opt_out=not mandatory) if u.id in wanted}
    taken: set[str] = set()
    to = _dedupe([by_id[i] for i in to_ids if i in by_id], taken)
    cc = _dedupe([by_id[i] for i in cc_ids if i in by_id], taken)
    if mandatory and not to:
        fallback = _users(db, admins_only=True, honour_opt_out=False) or _users(db, roles=["DevOps"], honour_opt_out=False)
        taken = {e.lower() for _, e in cc}
        to = _dedupe(fallback, taken)
    return to, cc


def list_recipient_options(db: Session) -> list[dict]:
    """Everyone who can be picked in the To / Cc boxes (used by the search list)."""
    q = db.query(User).filter(User.active.is_(True), User.status == "APPROVED", User.deleted.is_(False))
    return [
        {"id": u.id, "name": u.name or u.email, "email": u.email, "role": u.role,
         "emailOn": True, "admin": bool(u.role == "DevOps" and u.power)}
        for u in q.order_by(User.name).all() if u.email
    ]


def _url(path: str) -> str:
    return settings.APP_BASE_URL.rstrip("/") + path


def queue_password_reset_email(db: Session, user: User, otp: str) -> None:
    mail = Mail(
        eyebrow="OPSFlow account security",
        title="Password reset code",
        accent=NAVY,
        greeting=f"Hello {user.name or 'there'},",
        intro="Use the one-time code below to reset your OPSFlow password.",
        sections=[Section("Reset code", rows=[
            ("One-time code", otp),
            ("Expires in", f"{settings.OTP_TTL_MINUTES} minutes"),
        ])],
        warning="If you did not request a password reset, you can ignore this email.",
        preheader="Your OPSFlow password reset code.",
    )
    queue_email(db, OutgoingEmail(
        subject="[OPSFlow] Password reset code",
        html=render_html(mail),
        text=render_text(mail),
        to=[_pair(user)],
        actor_id=user.id,
        send_inline=True,
    ))


def queue_admin_created_user_email(db: Session, admin: User, user: User) -> None:
    mail = Mail(
        eyebrow="OPSFlow account",
        title="Your OPSFlow account is ready",
        accent=NAVY,
        greeting=f"Hello {user.name or 'there'},",
        intro=(f"An OPSFlow administrator created an account for you. Sign in at {_url('/')} "
               "using your company email and the initial password provided to you by your administrator."),
        sections=[Section("Sign-in details", rows=[
            ("Email", user.email),
            ("Role", user.role or ""),
        ])],
        warning="Keep your password private. Contact your administrator if you need help signing in.",
        preheader="Your OPSFlow account is ready to use.",
    )
    queue_email(db, OutgoingEmail(
        subject="[OPSFlow] Your account is ready",
        html=render_html(mail),
        text=render_text(mail),
        to=[_pair(user)],
        actor_id=admin.id,
        record_id=user.id,
        send_inline=True,
    ))


def _queue(db: Session, mail: Mail, subject: str, to, cc, actor: User | None, record_id: str = "") -> dict:
    """Queue the e-mail. Returns a small summary the API passes to the browser."""
    if not to:
        log.warning("No e-mail recipients for '%s' (everyone opted out?) — not sent.", subject)
        return {"queued": False, "to": [], "cc": [], "reason": "No one to send the e-mail to."}
    queue_email(db, OutgoingEmail(
        subject=subject, html=render_html(mail), text=render_text(mail), to=to, cc=cc,
        reply_to=_pair(actor) if actor else None,
        from_name=f"{actor.name} via OPSFlow" if actor else settings.MAIL_FROM_NAME,
        record_id=record_id, actor_id=actor.id if actor else "",
    ))
    return {"queued": True, "to": [n or e for n, e in to], "cc": [n or e for n, e in cc]}


NO_EMAIL = {"queued": False, "to": [], "cc": [], "reason": "E-mail was not requested."}


def _yes_no(flag) -> str:
    return "Yes" if flag else "No"


# ---------------------------------------------------------------------
# Deployment request
# ---------------------------------------------------------------------

def _env_var_names(raw) -> str:
    """Only the variable NAMES are e-mailed; values are secrets and stay in OPSFlow."""
    try:
        rows = json.loads(raw or "[]")
        names = [str(r.get("key", "")).strip() for r in rows if isinstance(r, dict) and str(r.get("key", "")).strip()]
    except (ValueError, TypeError):
        names = []
    return ", ".join(names) + "  (values hidden — view them in OPSFlow)" if names else ""


def deployment_created(db: Session, actor: User, dep, fields: dict, send_email: bool, conflict: dict | None,
                       to_ids=None, cc_ids=None, mandatory: bool = False,
                       resubmitted: bool = False) -> dict:
    try:
        to, cc = selected_recipients(db, to_ids, cc_ids, mandatory)
        env = dep.environment or "—"
        when = fmt_dt(dep.date_time)
        blocks = [("Application change details", (fields.get("applicationChangeDetails") or "").strip())]
        blocks = [b for b in blocks if b[1]]

        change = Section("Change scope", rows=[
            ("Database change", _yes_no(dep.db_change) + (f" — file: {dep.db_change_file_name}" if dep.db_change and dep.db_change_file_name else "")),
            ("Environment variables", _yes_no(dep.env_var_change)),
            ("Third-party API change", _yes_no(dep.third_party_api_change)),
        ], blocks=blocks)
        if dep.db_change and dep.db_change_details:
            change.blocks.append(("Database change details", dep.db_change_details))
        if dep.env_var_change and _env_var_names(dep.env_var_details):
            change.blocks.append(("Environment variables to add / update", _env_var_names(dep.env_var_details)))
        if dep.third_party_api_change and dep.third_party_api_details:
            change.blocks.append(("Third-party API details", dep.third_party_api_details))
        if dep.additional_info:
            change.blocks.append(("Additional information", dep.additional_info))

        warning = ""
        if conflict:
            warning = conflict.get("message", "")
            if conflict.get("conflictingId"):
                warning += f" (conflicting request: {conflict['conflictingId']})"

        mail = Mail(
            eyebrow="Deployment resubmission" if resubmitted else "Deployment request",
            title=f"{dep.id} — {dep.project or 'Deployment'} ({dep.component or '—'}) to {env}",
            accent=DEPLOYMENT_SKY,
            accent_text=DEPLOYMENT_SKY_TEXT,
            chips=[(env, RED if env.upper() == "PROD" else "#475569"), ("REQUESTED", "#0369a1")],
            greeting="Hello,",
            intro=(f"{actor.name} has {'resubmitted an updated' if resubmitted else 'raised a new'} deployment request "
                   f"for {dep.project or 'an application'} ({env}), scheduled for {when}. "
                   "Please review the details below and approve or reject it in OPSFlow."),
            warning=warning,
            sections=[
                Section("Request summary", rows=[
                    ("Request ID", dep.id), ("Project / App", dep.project), ("Component", dep.component),
                    ("Environment", env), ("Scheduled for", when),
                    ("Requested by", f"{actor.name} ({actor.role})"), ("Submitted at", fmt_dt(dep.created_at)),
                ]),
                Section("Source control", rows=[
                    ("GitHub URL", dep.github_url), ("Branch", dep.github_branch),
                    ("Application version", fields.get("appVersion")), ("Commit ID", dep.github_commit),
                    ("Rollback branch", dep.rollback_branch),
                ]),
                change,
            ],
            cta_label="Review request in OPSFlow", cta_url=_url(f"/deployments/{dep.id}"),
            sign_name=actor.name, sign_role=f"{actor.role}", sign_email=actor.email,
            preheader=f"{actor.name} requested a {env} deployment of {dep.project} for {when}.",
        )
        subject_type = "Deployment Request Resubmitted" if resubmitted else "Deployment Request"
        subject = f"[OPSFlow] {subject_type} {dep.id} | {dep.project or '-'} ({dep.component or '-'}) | {env} | {when}"
        return _queue(db, mail, subject, to, cc, actor, dep.id)
    except Exception:
        log.exception("Could not build deployment e-mail for %s", getattr(dep, "id", "?"))
        return {"queued": False, "to": [], "cc": [], "reason": "The e-mail could not be prepared."}


# ---------------------------------------------------------------------
# Deployment outcome: deployed successfully / failed / rolled back
# ---------------------------------------------------------------------

# status -> (eyebrow, chip text, chip/accent colour, subject word)
_OUTCOMES = {
    "COMPLETED_SUCCESS": ("Deployment successful", "DEPLOYED SUCCESSFULLY", SUCCESS_BG, SUCCESS_TEXT, "#15803d", "SUCCESSFUL"),
    "COMPLETED_FAILED": ("Deployment failed", "DEPLOYMENT FAILED", FAILURE_BG, FAILURE_TEXT, RED, "FAILED"),
    "ROLLED_BACK": ("Deployment rolled back", "ROLLED BACK", ROLLBACK_BG, ROLLBACK_TEXT, "#c2410c", "ROLLED BACK"),
    "REJECTED": ("Deployment rejected", "DEPLOYMENT REJECTED", FAILURE_BG, FAILURE_TEXT, RED, "REJECTED"),
}


def _outcome_recipients(db: Session, actor: User, dep) -> tuple[list, list]:
    """To = the people directly involved (requester, assigned DevOps engineer,
    admin(s)). Cc = every other active user who has e-mail on, plus the person
    who changed the status. Opted-out users are skipped everywhere."""
    involved_ids = {dep.requester_id, dep.assigned_devops_id}
    everyone = _users(db)
    to_users = [u for u in everyone if u.id in involved_ids]
    to_users += _users(db, admins_only=True)
    cc_users = ([actor] if wants_email(actor) else []) + everyone
    taken: set[str] = set()
    return _dedupe(to_users, taken), _dedupe(cc_users, taken)


def deployment_outcome(db: Session, actor: User, dep, new_status: str, reason: str | None,
                       send_email: bool = True, to_ids=None, cc_ids=None) -> None:
    """E-mail sent when a deployment ends: success, failure or rollback.

    to_ids / cc_ids = the people the admin / DevOps engineer picked in the To / Cc boxes.
    When none are sent (older callers, voice) the default recipient rule is used.
    """
    meta = _OUTCOMES.get(new_status)
    picked = bool(_ids(to_ids))
    if not meta:
        return
    try:
        eyebrow, chip_text, colour, accent_text, chip_colour, word = meta
        if picked:
            to, cc = selected_recipients(db, to_ids, cc_ids, mandatory=True)
        else:
            to, cc = _outcome_recipients(db, actor, dep)
        env = dep.environment or "—"
        requester = db.get(User, dep.requester_id) if dep.requester_id else None
        engineer = db.get(User, dep.assigned_devops_id) if dep.assigned_devops_id else None
        name = f"{dep.project or 'Deployment'} ({dep.component or '—'})"

        if new_status == "REJECTED":
            intro = (f"The deployment request {dep.id} — {name} to {env} was rejected by {actor.name}. "
                     "Please review the rejection reason below.")
        elif new_status == "COMPLETED_SUCCESS":
            intro = (f"{dep.id} — {name} was deployed successfully to {env} by {actor.name}. "
                     f"No further action is needed.")
        elif new_status == "COMPLETED_FAILED":
            intro = (f"The deployment {dep.id} — {name} to {env} has FAILED (marked by {actor.name}). "
                     f"Please review the failure reason below.")
        else:
            intro = (f"The deployment {dep.id} — {name} to {env} was ROLLED BACK by {actor.name}. "
                     f"Please review the rollback reason below and verify the application.")

        blocks = []
        if new_status == "REJECTED" and reason:
            blocks.append(("Rejection reason", reason))
        if new_status == "COMPLETED_FAILED" and reason:
            blocks.append(("Failure reason", reason))
        if new_status == "ROLLED_BACK":
            if reason:
                blocks.append(("Rollback reason", reason))
        summary_rows = [
            ("Request ID", dep.id), ("Project / App", dep.project), ("Component", dep.component),
            ("Environment", env), ("Scheduled for", fmt_dt(dep.date_time)),
            ("Outcome", chip_text.title()),
            ("Updated by", f"{actor.name} ({actor.role})"), ("Updated at", fmt_dt(dep.resolved_at or dep.updated_at)),
            ("Requested by", f"{requester.name} ({requester.role})" if requester else "—"),
            ("Assigned DevOps", engineer.name if engineer else "—"),
        ]
        source_rows = [
            ("GitHub URL", dep.github_url), ("Branch", dep.github_branch), ("Commit ID", dep.github_commit),
        ]
        if new_status == "ROLLED_BACK":
            source_rows.append(("Rolled back to branch", dep.rollback_branch))

        mail = Mail(
            eyebrow=eyebrow,
            title=f"{dep.id} — {name} on {env}",
            accent=colour,
            accent_text=accent_text,
            chips=[(chip_text, chip_colour), (env, RED if env.upper() == "PROD" else "#475569")],
            greeting="Hello Team,",
            intro=intro,
            warning=("Production deployment — please verify the application." if env.upper() == "PROD" and new_status != "COMPLETED_SUCCESS" else ""),
            sections=[
                Section("Deployment summary", rows=summary_rows, blocks=blocks),
                Section("Source control", rows=source_rows),
            ],
            cta_label="View deployment in OPSFlow", cta_url=_url(f"/deployments/{dep.id}"),
            sign_name=actor.name, sign_role=f"{actor.role}", sign_email=actor.email,
            preheader=f"{dep.id} {word.lower()} on {env} — {dep.project or ''}",
        )
        subject = f"[OPSFlow] Deployment {word} | {dep.id} | {dep.project or '-'} ({dep.component or '-'}) | {env}"
        _queue(db, mail, subject, to, cc, actor, dep.id)
    except Exception:
        log.exception("Could not build deployment outcome e-mail for %s", getattr(dep, "id", "?"))


# ---------------------------------------------------------------------
# Access request
# ---------------------------------------------------------------------

def access_created(db: Session, actor: User, acc, send_email: bool, to_ids=None, cc_ids=None,
                   mandatory: bool = False) -> dict:
    try:
        to, cc = selected_recipients(db, to_ids, cc_ids, mandatory)
        env = acc.environment or "—"
        mail = Mail(
            eyebrow="Access request",
            title=f"{acc.id} — {acc.access_type or 'Access'} on {acc.project or '—'} ({env})",
            accent=ACCESS_BG,
            accent_text=ACCESS_TEXT,
            chips=[(env, RED if env.upper() == "PROD" else "#475569"), ("REQUESTED", "#0369a1")],
            greeting="Hello,",
            intro=(f"{actor.name} has requested {acc.access_type or 'access'} for {acc.project or 'an application'} "
                   f"({env}). Please review the request and grant or reject it in OPSFlow."),
            sections=[
                Section("Request summary", rows=[
                    ("Request ID", acc.id), ("Access type", acc.access_type), ("Project / App", acc.project),
                    ("Environment", env), ("User / resource", acc.user_resource),
                    ("Access level", acc.permission), ("Access expires", acc.expiry_date),
                    ("Requested by", f"{actor.name} ({actor.role})"), ("Submitted at", fmt_dt(acc.created_at)),
                ], blocks=[("Reason / business justification", acc.reason)] if acc.reason else []),
            ],
            cta_label="Review request in OPSFlow", cta_url=_url(f"/access/{acc.id}"),
            sign_name=actor.name, sign_role=f"{actor.role}", sign_email=actor.email,
            preheader=f"{actor.name} requested {acc.access_type} access on {acc.project} ({env}).",
        )
        subject = f"[OPSFlow] Access Request {acc.id} | {acc.access_type or '-'} on {acc.project or '-'} ({env})"
        return _queue(db, mail, subject, to, cc, actor, acc.id)
    except Exception:
        log.exception("Could not build access e-mail for %s", getattr(acc, "id", "?"))
        return {"queued": False, "to": [], "cc": [], "reason": "The e-mail could not be prepared."}


def _access_outcome_recipients(db: Session, actor: User, acc) -> tuple[list, list]:
    requester = db.get(User, acc.requester_id) if acc.requester_id else None
    admins = _users(db, admins_only=True, honour_opt_out=False)
    taken: set[str] = set()
    to = _dedupe(([requester] if requester else []) + admins, taken)
    if actor.email.lower() not in taken:
        to = [recipient for recipient in to if recipient[1].lower() != actor.email.lower()]
    return to, []


def access_status_changed(db: Session, actor: User, acc, new_status: str, reason: str | None,
                          to_ids=None, cc_ids=None) -> dict:
    if new_status not in ("ACCESS_GIVEN", "REJECTED"):
        return NO_EMAIL
    try:
        if _ids(to_ids):
            to, cc = selected_recipients(db, to_ids, cc_ids, mandatory=True)
        else:
            to, cc = _access_outcome_recipients(db, actor, acc)
        given = new_status == "ACCESS_GIVEN"
        status_label = "ACCESS GIVEN" if given else "ACCESS REJECTED"
        accent_text = ACCESS_TEXT
        accent = ACCESS_BG
        chip_colour = "#4d7c0f"
        requester = db.get(User, acc.requester_id) if acc.requester_id else None
        mail = Mail(
            eyebrow="Access request update",
            title=f"{acc.id} — {status_label.title()}",
            accent=accent,
            accent_text=accent_text,
            chips=[(status_label, chip_colour), (acc.environment or "—", "#475569")],
            greeting=f"Hello {requester.name if requester else 'there'},",
            intro=(
                f"Your access request for {acc.access_type or 'access'} on {acc.project or 'an application'} "
                f"was {'granted' if given else 'rejected'} by {actor.name}."
            ),
            sections=[Section("Request update", rows=[
                ("Request ID", acc.id), ("Project / App", acc.project), ("Access type", acc.access_type),
                ("Environment", acc.environment), ("User / resource", acc.user_resource),
                ("Access level", acc.permission), ("Access expires", acc.expiry_date),
                ("Status", status_label.title()), ("Updated by", f"{actor.name} ({actor.role})"),
                ("Updated at", fmt_dt(acc.updated_at)),
            ], blocks=[("Reason", reason)] if reason else [])],
            cta_label="View access request in OPSFlow", cta_url=_url(f"/access/{acc.id}"),
            sign_name=actor.name, sign_role=actor.role, sign_email=actor.email,
            preheader=f"Access request {acc.id} was {status_label.lower()}.",
        )
        subject = f"[OPSFlow] Access {status_label.title()} | {acc.id} | {acc.project or '-'}"
        return _queue(db, mail, subject, to, cc, actor, acc.id)
    except Exception:
        log.exception("Could not build access status e-mail for %s", getattr(acc, "id", "?"))
        return {"queued": False, "to": [], "cc": [], "reason": "The e-mail could not be prepared."}


# ---------------------------------------------------------------------
# AWS issue
# ---------------------------------------------------------------------

def aws_issue_created(db: Session, actor: User, issue, send_email: bool, to_ids=None, cc_ids=None) -> dict:
    try:
        to, cc = selected_recipients(db, to_ids, cc_ids)
        prio = issue.priority or "High"
        colour = PRIORITY_COLOURS.get(prio, SLATE)
        service = issue.service or "—"
        mail = Mail(
            eyebrow="AWS issue",
            title=f"{issue.id} — {service} issue in {issue.project or '—'} ({issue.environment or 'PROD'})",
            accent=colour,
            chips=[(f"{prio.upper()} PRIORITY", "#111827"), (issue.environment or "PROD", "#475569"), ("OPEN", "#0369a1")],
            greeting="Hello Team,",
            intro=(f"{actor.name} has reported a {prio.lower()}-priority AWS issue affecting {service} on "
                   f"{issue.project or 'an application'}. Please review it in OPSFlow."),
            sections=[
                Section("Issue summary", rows=[
                    ("Issue ID", issue.id), ("AWS service", service), ("Project / App", issue.project),
                    ("Environment", issue.environment), ("Priority", prio), ("Reported at", fmt_dt(issue.date_time)),
                    ("Reported by", f"{actor.name} ({actor.role})"),
                ], blocks=[b for b in [
                    ("Error message", issue.error_message), ("Symptoms", issue.symptoms), ("Business impact", issue.impact),
                ] if b[1]]),
            ],
            cta_label="Open issue in OPSFlow", cta_url=_url(f"/aws-issues/{issue.id}"),
            sign_name=actor.name, sign_role=f"{actor.role}", sign_email=actor.email,
            preheader=f"{prio} AWS issue on {service} — {(issue.error_message or '')[:100]}",
        )
        subject = f"[OPSFlow] [{prio.upper()}] AWS Issue {issue.id} | {service} - {issue.project or '-'} ({issue.environment or 'PROD'})"
        return _queue(db, mail, subject, to, cc, actor, issue.id)
    except Exception:
        log.exception("Could not build AWS issue e-mail for %s", getattr(issue, "id", "?"))
        return {"queued": False, "to": [], "cc": [], "reason": "The e-mail could not be prepared."}


# ---------------------------------------------------------------------
# New user registration -> admins
# ---------------------------------------------------------------------

def user_registered(db: Session, user: User, role: str) -> None:
    try:
        to = _dedupe(_users(db, admins_only=True), set())
        mail = Mail(
            eyebrow="User registration",
            title=f"New user awaiting approval — {user.name}",
            accent=NAVY,
            chips=[(f"REQUESTED ROLE: {role.upper()}", "#0369a1"), ("PENDING", "#b45309")],
            greeting="Hello Admin,",
            intro=(f"{user.name} has registered on OPSFlow and is waiting for your approval. "
                   f"The account stays locked until you review it under User Management."),
            sections=[Section("Registration details", rows=[
                ("User ID", user.id), ("Full name", user.name), ("Work e-mail", user.email),
                ("Mobile number", user.mobile), ("Requested role", role),
                ("Registered at", fmt_dt(user.created_at)), ("Status", "Pending approval"),
            ])],
            cta_label="Review in User Management", cta_url=_url("/users"),
            sign_name="OPSFlow", preheader=f"{user.name} ({user.email}) registered as {role}.",
        )
        _queue(db, mail, f"[OPSFlow] New user registration awaiting approval | {user.name} ({role})", to, [], None)
    except Exception:
        log.exception("Could not build registration e-mail for %s", getattr(user, "id", "?"))