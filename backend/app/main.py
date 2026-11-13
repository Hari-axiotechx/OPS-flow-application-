"""
OPSFlow backend — FastAPI + PostgreSQL.

The React frontend (unchanged) talks to one URL with an `action` field,
GET for reads / POST for writes — that's how it was built against the
old Google Apps Script backend. Rather than rewrite the frontend, this
FastAPI app exposes the exact same contract, so all you do is point
VITE_API_URL at this server (see frontend/.env.example) instead of the
old /exec URL.
"""
import json
from datetime import datetime

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .database import get_db
from .config import settings
from .auth_helpers import authenticate
from .errors import ApiError
from .seed import run_seed
from . import logic, mailer, voice, voice_form, voice_stt, llm

app = FastAPI(title="OPSFlow API")

# Compress JSON answers (lists of records shrink a lot) -> pages load faster.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    run_seed()
    llm.warmup()   # open the AI connection now, not on the first voice command
    # Print the e-mail settings and test the mail login in the background, so a broken set-up
    # shows up in `docker compose logs backend` straight away instead of on the first request.
    import threading
    threading.Thread(target=mailer.startup_report, name="opsflow-mail-check", daemon=True).start()


def _default_json(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o)} is not JSON serializable")


def _ok(data):
    return json.loads(json.dumps({"ok": True, "data": data}, default=_default_json))


def _err(message: str):
    return {"ok": False, "error": message}


GET_ACTIONS = {
    "ping": lambda db, params, ctx: {"ok": True, "time": logic.now().isoformat()},
    "bootstrap": lambda db, params, ctx: logic.handle_bootstrap(db, ctx),
    "listRecords": lambda db, params, ctx: logic.handle_list_records(db, params, ctx),
    "getRecord": lambda db, params, ctx: logic.handle_get_record(db, params.get("id"), ctx),
    "search": lambda db, params, ctx: logic.handle_search(db, params.get("q"), ctx),
    "listUsers": lambda db, params, ctx: logic.handle_list_users(db, ctx),
    "listDevOpsUsers": lambda db, params, ctx: logic.handle_list_devops_users(db, ctx),
    "listEmailRecipients": lambda db, params, ctx: logic.handle_list_email_recipients(db, ctx),
    "getConfig": lambda db, params, ctx: logic.handle_get_config(db),
    "listNotifications": lambda db, params, ctx: logic.handle_list_notifications(db, params, ctx),
    "listApplications": lambda db, params, ctx: logic.handle_list_applications(db, ctx),
}

POST_ACTIONS = {
    "register": lambda db, body, ctx: logic.handle_register(db, body),
    "login": lambda db, body, ctx: logic.handle_login(db, body),
    "requestPasswordReset": lambda db, body, ctx: logic.handle_request_password_reset(db, body),
    "resetPassword": lambda db, body, ctx: logic.handle_reset_password(db, body),
    "updateProfile": lambda db, body, ctx: logic.handle_update_profile(db, body, ctx),

    "createDeployment": lambda db, body, ctx: logic.handle_create_deployment(db, body, ctx),
    "resubmitDeployment": lambda db, body, ctx: logic.handle_resubmit_deployment(db, body, ctx),
    "updateDeploymentStatus": lambda db, body, ctx: logic.handle_update_deployment_status(db, body, ctx),
    "updateDeployment": lambda db, body, ctx: logic.handle_update_deployment(db, body, ctx),
    # Assigning a deployment is Admin-only (see handle_reassign_deployment).
    # DevOps users have no assignment power — the old "request reassignment"
    # route that let a DevOps user hand a deployment to someone else has
    # been removed on purpose.
    "reassignDeployment": lambda db, body, ctx: logic.handle_reassign_deployment(db, body, ctx),

    "createAccess": lambda db, body, ctx: logic.handle_create_access(db, body, ctx),
    "updateAccessStatus": lambda db, body, ctx: logic.handle_update_access_status(db, body, ctx),

    "createIssue": lambda db, body, ctx: logic.handle_create_issue(db, body, ctx),
    "updateIssue": lambda db, body, ctx: logic.handle_update_issue(db, body, ctx),

    "createAwsIssue": lambda db, body, ctx: logic.handle_create_aws_issue(db, body, ctx),
    "updateAwsIssue": lambda db, body, ctx: logic.handle_update_aws_issue(db, body, ctx),
    "reopenAwsIssue": lambda db, body, ctx: logic.handle_reopen_aws_issue(db, body, ctx),

    "softDeleteRecord": lambda db, body, ctx: logic.handle_soft_delete(db, body, ctx),

    "adminApproveUser": lambda db, body, ctx: logic.handle_admin_approve_user(db, body, ctx),
    "adminRejectUser": lambda db, body, ctx: logic.handle_admin_reject_user(db, body, ctx),
    "adminCreateUser": lambda db, body, ctx: logic.handle_admin_create_user(db, body, ctx),
    "adminUpdateUser": lambda db, body, ctx: logic.handle_admin_update_user(db, body, ctx),
    "adminDeactivateUser": lambda db, body, ctx: logic.handle_admin_deactivate_user(db, body, ctx),
    "adminAddConfigValue": lambda db, body, ctx: logic.handle_admin_add_config_value(db, body, ctx),
    "adminAddApplication": lambda db, body, ctx: logic.handle_admin_add_application(db, body, ctx),
    "adminRemoveApplication": lambda db, body, ctx: logic.handle_admin_remove_application(db, body, ctx),

    # Voice assistant: text in -> spoken answer + UI action out (see app/voice.py).
    "voiceCommand": lambda db, body, ctx: voice.handle_voice_command(db, body, ctx),
    # Guided form filling by voice: values the user speaks -> patch for the visible form (never submits).
    "voiceForm": lambda db, body, ctx: voice_form.handle_voice_form(db, body, ctx),
    # Sent the moment "Hello Ops" is heard: opens the AI connection in the background so the answer is faster.
    # Short-lived token so the browser can stream microphone audio to the speech-to-text service.
    "voiceSttToken": lambda db, body, ctx: voice_stt.handle_voice_stt_token(db, body, ctx),
    "voiceWarmup": lambda db, body, ctx: {"ai": llm.warmup()},

    # Admin only: sends a real test e-mail now and returns the mail server's answer (diagnostics).
    "sendTestEmail": lambda db, body, ctx: logic.handle_send_test_email(db, body, ctx),

    "markNotificationRead": lambda db, body, ctx: logic.handle_mark_notification_read(db, body, ctx),
    "deleteNotification": lambda db, body, ctx: logic.handle_delete_notification(db, body, ctx),
    "markAllNotificationsRead": lambda db, body, ctx: logic.handle_mark_all_notifications_read(db, body, ctx),
}


def _run(handler, db: Session, args: dict, ctx):
    """Runs one action (sync DB / AI work) and commits. Called in a worker thread."""
    try:
        result = handler(db, args, ctx)
        db.commit()
    except ApiError as e:
        db.rollback()
        mailer.discard_pending(db)
        return _err(str(e))
    except Exception as e:  # pragma: no cover - safety net, mirrors original catch-all
        db.rollback()
        mailer.discard_pending(db)
        return _err(str(e))
    # The request is saved. E-mails go out only now, and a problem handing them to the sender
    # can never turn a saved request into an error.
    mailer.dispatch_pending(db)
    try:
        return _ok(result)
    except Exception as e:  # result could not be turned into JSON
        return _err(str(e))


# SPEED: every action runs in the thread pool. Before, POST handlers ran the
# database / e-mail / AI work directly inside the async event loop, so one slow
# call (for example an AI request) froze EVERY other request of every user
# until it finished (notifications, page loads, the next voice command...).

@app.get("/api")
async def api_get(request: Request, db: Session = Depends(get_db)):
    params = dict(request.query_params)
    action = (params.get("action") or "").strip()
    handler = GET_ACTIONS.get(action)
    if not handler:
        return _err(f"Unknown GET action: {action}")

    def work():
        ctx = authenticate(db, params.get("token"))
        return _run(handler, db, params, ctx)
    return await run_in_threadpool(work)


@app.post("/api")
async def api_post(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return _err("Invalid request body.")
    action = body.get("action")
    handler = POST_ACTIONS.get(action)
    if not handler:
        return _err(f"Unknown POST action: {action}")

    def work():
        ctx = authenticate(db, body.get("token"))
        return _run(handler, db, body, ctx)
    return await run_in_threadpool(work)


@app.get("/health")
def health():
    return {"status": "ok"}