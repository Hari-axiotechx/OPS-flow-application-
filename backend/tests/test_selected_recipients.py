# Run from the backend folder:  python tests/test_selected_recipients.py
# Deployment / Access / AWS-issue e-mails go ONLY to the people picked in the To / Cc boxes.
import os, sys
# The app's first (unused) engine config includes QueuePool options, which
# SQLite only accepts with a file-backed URL. The test replaces this engine
# immediately with its own in-memory StaticPool engine below.
os.environ["DATABASE_URL"] = "sqlite:///./unused-test.db"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.database as database
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
database.engine = engine
Session = sessionmaker(bind=engine)
from app import models, logic, ids, email_events
from app.config import settings
from app.errors import ApiError
from app.auth_helpers import Ctx
database.Base.metadata.create_all(engine)

_c = {}
def gen(db, rt):
    _c[rt] = _c.get(rt, 0) + 1
    return f"{ids.PREFIXES[rt]}-{_c[rt]:06d}"
logic.generate_id = gen
logic.generate_deployment_id = lambda db, project: gen(db, "DEPLOYMENT")

db = Session()
def user(i, name, email, role, power=False, prefs=None):
    u = models.User(id=i, name=name, email=email, password_hash="x", role=role, power=power, active=True,
                    status="APPROVED", preferences=prefs or {})
    db.add(u); return u
admin = user("USR-1", "Hari Admin", "hari@axiotechx.com", "DevOps", True)
eng   = user("USR-2", "Eswar DevOps", "eswar@axiotechx.com", "DevOps")
dev   = user("USR-3", "Keshava Dev", "keshava@axiotechx.com", "Developer")
qa    = user("USR-4", "Quincy QA", "qa@axiotechx.com", "QA")
quiet = user("USR-5", "Quiet Dev", "quiet@axiotechx.com", "Developer", prefs={"emailNotifications": False})
db.commit()
def ctx(u): return Ctx(email=u.email, user=u)

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  PASS", label)
    else: fail += 1; print("  FAIL", label, extra)

def pending():
    return db.info.pop("pending_emails", [])
def addrs(pairs): return sorted(e for _, e in pairs)

ACCESS = {"accessType": "RDS", "project": "PG-Desk", "environment": "PROD", "userResource": "keshava",
          "permission": "Read Only", "reason": "Debug", "expiryDate": "2030-01-01"}
AWS = {"project": "PG-Desk", "service": "RDS", "errorMessage": "Timeout", "impact": "Login down"}
DEP = {"project": "PG-Desk", "component": "Frontend", "environment": "PROD", "dateTime": "2030-01-01T10:00",
       "githubUrl": "https://github.com/axiotechx/x", "githubBranch": "main"}

print("== sender ==")
check("default sender is no-reply@axiotechx.com", settings.MAIL_FROM_ADDRESS == "no-reply@axiotechx.com", settings.MAIL_FROM_ADDRESS)

print("== recipient list for the search box ==")
opts = email_events.list_recipient_options(db)
check("all 5 active users listed", len(opts) == 5)
check("legacy opt-out does not disable email", [o for o in opts if o["id"] == "USR-5"][0]["emailOn"] is True)

print("== access request ==")
r = logic.handle_create_access(db, {"fields": ACCESS, "sendEmail": True,
        "emailTo": ["USR-1"], "emailCc": ["USR-2", "USR-4"]}, ctx(dev))
m = pending()
check("one mail queued", len(m) == 1)
check("To = only the selected person", addrs(m[0].to) == ["hari@axiotechx.com"], m[0].to)
check("Cc = only the selected people", addrs(m[0].cc) == ["eswar@axiotechx.com", "qa@axiotechx.com"], m[0].cc)
check("requester NOT auto-copied", "keshava@axiotechx.com" not in addrs(m[0].to + m[0].cc))
check("reply-to is the requester", m[0].reply_to and m[0].reply_to[1] == "keshava@axiotechx.com")

print("== rules ==")
try:
    logic.handle_create_access(db, {"fields": ACCESS, "sendEmail": True, "emailTo": [], "emailCc": ["USR-2"]}, ctx(dev))
    check("ticked + no To -> refused", False)
except ApiError as e:
    check("ticked + no To -> refused", "To" in str(e)); db.rollback(); pending()
try:
    logic.handle_create_access(db, {"fields": ACCESS, "sendEmail": False, "emailTo": [], "emailCc": []}, ctx(dev))
    check("access: legacy sendEmail=false with no To -> still refused", False)
except ApiError:
    check("access: legacy sendEmail=false with no To -> still refused", True); db.rollback(); pending()
r = logic.handle_create_access(db, {"fields": ACCESS, "sendEmail": False, "emailTo": ["USR-1"], "emailCc": []}, ctx(dev))
check("access: sendEmail=false is ignored, mail is sent anyway", len(pending()) == 1)
check("access: API tells the browser who gets the mail", r["email"]["queued"] and r["email"]["to"] == ["Hari Admin"], r.get("email"))
logic.handle_create_access(db, {"fields": ACCESS, "sendEmail": True, "emailTo": ["USR-1", "USR-5"], "emailCc": ["USR-1", "USR-2"]}, ctx(dev))
m = pending()[0]
check("mandatory mail still reaches a person whose profile e-mail switch is off", "quiet@axiotechx.com" in addrs(m.to + m.cc), (m.to, m.cc))
check("same person in To and Cc stays in To only", addrs(m.to) == ["hari@axiotechx.com", "quiet@axiotechx.com"] and addrs(m.cc) == ["eswar@axiotechx.com"], (m.to, m.cc))
logic.handle_create_access(db, {"fields": ACCESS, "sendEmail": True, "emailTo": ["USR-1"]}, ctx(quiet))
m = pending()
check("requester opted out in Profile -> access mail is STILL sent", len(m) == 1 and addrs(m[0].to) == ["hari@axiotechx.com"], m and m[0].to)
logic.handle_create_access(db, {"fields": ACCESS, "sendEmail": True, "emailTo": ["USR-999", "evil@x.com"]}, ctx(dev))
m = pending()
check("unknown ids / typed addresses never mailed; DevOps admin gets it instead of dropping it",
      len(m) == 1 and addrs(m[0].to + m[0].cc) == ["hari@axiotechx.com"], m and (m[0].to, m[0].cc))

print("== deployment request ==")
logic.handle_create_deployment(db, {"fields": DEP, "sendEmail": True, "emailTo": ["USR-2", "USR-1"], "emailCc": ["USR-4"]}, ctx(dev))
m = pending()
check("deployment mail To/Cc as picked", len(m) == 1 and addrs(m[0].to) == ["eswar@axiotechx.com", "hari@axiotechx.com"] and addrs(m[0].cc) == ["qa@axiotechx.com"], m and (m[0].to, m[0].cc))

try:
    logic.handle_create_deployment(db, {"fields": DEP, "sendEmail": False, "emailTo": []}, ctx(dev))
    check("deployment: no To -> refused (mail is mandatory)", False)
except ApiError as e:
    check("deployment: no To -> refused (mail is mandatory)", "To" in str(e)); db.rollback(); pending()
r = logic.handle_create_deployment(db, {"fields": DEP, "sendEmail": False, "emailTo": ["USR-1"]}, ctx(dev))
check("deployment: sendEmail=false ignored, mail sent", len(pending()) == 1 and r["email"]["queued"])
logic.handle_create_deployment(db, {"fields": DEP, "emailTo": ["USR-1"]}, ctx(quiet))
check("deployment: requester with e-mail switch off still sends", len(pending()) == 1)
check("recipient list marks DevOps admins (used to pre-fill 'To')",
      [o["id"] for o in email_events.list_recipient_options(db) if o["admin"]] == ["USR-1"])

print("== rejected deployment resubmission ==")
rejected_request = logic.handle_create_deployment(
    db, {"fields": {**DEP, "dateTime": "2031-01-15T10:00"}, "emailTo": ["USR-1"]}, ctx(dev)
)
pending()
rejected_result = logic.handle_update_deployment_status(
    db, {
        "id": rejected_request["record"]["Record ID"],
        "newStatus": "REJECTED",
        "reason": "Please update the rollout plan.",
        "emailTo": ["USR-3", "USR-1"],
    }, ctx(admin)
)
rejected_mail = pending()
check("reject action queues an email to selected requester and admin",
      rejected_result["newStatus"] == "REJECTED" and len(rejected_mail) == 1
      and addrs(rejected_mail[0].to) == ["hari@axiotechx.com", "keshava@axiotechx.com"])
check("rejection email includes the reason and red failure accent",
      "Please update the rollout plan." in rejected_mail[0].html and "#fee2e2" in rejected_mail[0].html)

resubmit_fields = {**DEP, "project": "Resubmit Test", "dateTime": "2031-02-01T10:00"}
created = logic.handle_create_deployment(
    db, {"fields": resubmit_fields, "emailTo": ["USR-1"]}, ctx(dev)
)
pending()
resubmit_dep = db.get(models.Deployment, created["record"]["Record ID"])
resubmit_dep.status = "REJECTED"
resubmit_dep.rejection_reason = "Please correct the rollout details."
resubmit_dep.failure_reason = "stale failure"
resubmit_dep.rollback_reason = "stale rollback"
resubmit_dep.resolved_by = admin.email
resubmit_dep.resolved_at = logic.now()
db.flush()
try:
    logic.handle_resubmit_deployment(
        db, {"id": resubmit_dep.id, "fields": resubmit_fields, "emailTo": ["USR-1"]}, ctx(qa)
    )
    check("another requester cannot edit and resubmit", False)
except ApiError:
    check("another requester cannot edit and resubmit", resubmit_dep.status == "REJECTED")

resubmit_fields["githubBranch"] = "release"
resubmitted = logic.handle_resubmit_deployment(
    db, {"id": resubmit_dep.id, "fields": resubmit_fields, "emailTo": ["USR-1"]}, ctx(dev)
)
mail = pending()
check("requester can resubmit their rejected deployment", resubmitted["record"]["Status"] == "REQUESTED")
check("resubmission updates the edited fields", resubmit_dep.github_branch == "release")
check("resubmission clears rejection and stale resolution details",
      not resubmit_dep.rejection_reason and not resubmit_dep.failure_reason
      and not resubmit_dep.rollback_reason and resubmit_dep.resolved_by is None
      and resubmit_dep.resolved_at is None)
check("resubmission queues the mandatory deployment email with the sky-blue accent",
      len(mail) == 1 and mail[0].to[0][1] == "hari@axiotechx.com"
      and "Resubmitted" in mail[0].subject and "#e0f2fe" in mail[0].html)

access_created = logic.handle_create_access(
    db, {"fields": ACCESS, "emailTo": ["USR-1"]}, ctx(dev)
)
pending()
access_record = db.get(models.AccessRequest, access_created["record"]["Record ID"])
email_events.access_status_changed(db, admin, access_record, "REJECTED", "Not approved", ["USR-1"], [])
access_mail = pending()
check("rejected access-request emails retain the yellow-green access accent",
      len(access_mail) == 1 and "#ecfccb" in access_mail[0].html and "#fee2e2" not in access_mail[0].html)

print("== AWS (production) issue ==")
logic.handle_create_aws_issue(db, {"fields": AWS, "sendEmail": True, "emailTo": ["USR-3"], "emailCc": ["USR-1"]}, ctx(admin))
m = pending()
check("AWS issue now sends mail", len(m) == 1 and "AWS Issue" in m[0].subject)
check("AWS To/Cc as picked", addrs(m[0].to) == ["keshava@axiotechx.com"] and addrs(m[0].cc) == ["hari@axiotechx.com"])
logic.handle_create_aws_issue(db, {"fields": AWS, "sendEmail": False, "emailTo": ["USR-5"]}, ctx(admin))
m = pending()
check("legacy opt-out and sendEmail=false cannot disable AWS email",
      len(m) == 1 and addrs(m[0].to) == ["quiet@axiotechx.com"], m and m[0].to)
try:
    logic.handle_create_aws_issue(db, {"fields": AWS, "sendEmail": True, "emailTo": []}, ctx(admin))
    check("AWS email with no To -> refused", False)
except ApiError:
    check("AWS email with no To -> refused", True); db.rollback(); pending()

print(f"\nRESULT: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
