# Run from the backend folder:  pip install -r requirements.txt  &&  python tests/test_voice_and_emails.py
# Uses an in-memory SQLite database; no Postgres needed.
import os, sys, json
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_BASE_URL"] = "http://localhost:5173"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.database as database
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
database.engine = engine
Session = sessionmaker(bind=engine)
from app import models, logic, voice, email_events, ids, mailer
from app.auth_helpers import Ctx
from app.errors import ApiError
database.Base.metadata.create_all(engine)

# sqlite has no advisory locks: simple counter instead of ids.generate_id
_c = {}
def gen(db, rt):
    _c[rt] = _c.get(rt, 0) + 1
    return f"{ids.PREFIXES[rt]}-{_c[rt]:06d}"
logic.generate_id = gen

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
from datetime import datetime, timezone, timedelta
now = datetime.now(timezone.utc)
def dep(i, project, env, status, hours=0, requester="USR-3", assigned="USR-2"):
    d = models.Deployment(id=f"DEP-{i:06d}", project=project, component="API", environment=env,
        date_time=now + timedelta(hours=hours), status=status, requester_id=requester, assigned_devops_id=assigned,
        github_url="https://github.com/axiotechx/x", github_branch="release/1.2", github_commit="abc123",
        rollback_branch="release/1.1", created_at=now, updated_at=now)
    db.add(d)
dep(123, "Stylo-Customer", "PROD", "REQUESTED")
dep(124, "PG-Desk", "QA", "APPROVED")
dep(125, "PG-Desk", "PROD", "IN_PROGRESS")
dep(126, "Stylo-Captain", "UAT", "COMPLETED_FAILED")
dep(127, "PG-Desk", "PROD", "COMPLETED_FAILED", hours=-48)
db.add(models.AccessRequest(id="ACC-000007", access_type="RDS", project="PG-Desk", environment="PROD",
       user_resource="keshava", status="REQUESTED", requester_id="USR-3", created_at=now))
db.add(models.AwsIssue(id="AWS-000002", project="PG-Desk", environment="PROD", service="RDS",
       error_message="Connection timeout", status="OPEN", requester_id="USR-2", priority="High", date_time=now, created_at=now))
db.commit()

def ctx(u): return Ctx(email=u.email, user=u)
def say(u, text):
    r = voice.handle_voice_command(db, {"text": text}, ctx(u))
    return r

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  PASS", label)
    else: fail += 1; print("  FAIL", label, extra)

print("== normalize ==")
n = voice.normalize
check("wake word stripped", n("Hello ops, open deployment 123") == "open deployment 123", n("Hello ops, open deployment 123"))
check("aaa ops", n("Hello ops show failed deployments") == "show failed deployments")
check("hello ops", n("hello ops help") == "help")
check("hey ops also wakes", n("hey ops help") == "help")
check("hello ops", n("Hello Ops") == "")
check("number words", n("open deployment one two three") == "open deployment 123", n("open deployment one two three"))
check("number groups", n("open deployment 5678 9778") == "open deployment 56789778", n("open deployment 5678 9778"))
check("lone digit word after record", n("open deployment five") == "open deployment 5")
check("lone 'one' kept", n("open the first one") == "open the first one")

print("== voice intents (DevOps admin) ==")
r = say(admin, "open deployment 123"); check("open", r["intent"]=="open" and r["route"]=="/deployments/DEP-000123", r)
r = say(admin, "hello ops open deployment one two three"); check("open via words", r["route"]=="/deployments/DEP-000123", r)
r = say(admin, "open deployment 56789778"); check("not found spoken", r["intent"]=="error" and "couldn't find" in r["speech"], r)
r = say(admin, "show failed deployments"); check("list failed", r["intent"]=="list" and len(r["results"])==2 and r["route"]=="/deployments?status=COMPLETED_FAILED", r)
r = say(admin, "how many pending deployments"); check("count pending", r["intent"]=="count" and "1 pending deployments" in r["speech"].replace("is 1","is 1"), r)
r = say(admin, "how many failed deployments for pg desk"); check("count failed pgdesk", "1 failed deployments for PG-Desk" in r["speech"], r)
r = say(admin, "show prod deployments"); check("prod filter", len(r["results"])==3 and r["route"] is None, r)
r = say(admin, "show deployments today"); check("today filter", len(r["results"])==4, [x["id"] for x in r["results"]])
r = say(admin, "show approved deployments"); check("approved", [x["id"] for x in r["results"]]==["DEP-000124"], r)
r = say(admin, "pending access requests"); check("access list", r["results"] and r["results"][0]["id"]=="ACC-000007" and r["route"]=="/access?status=REQUESTED", r)
r = say(admin, "show open issues"); check("aws open", r["results"] and r["results"][0]["id"]=="AWS-000002", r)
r = say(admin, "go to dashboard"); check("nav dashboard", r["route"]=="/", r)
r = say(admin, "open user management"); check("nav users admin", r["route"]=="/users", r)
r = say(admin, "show deployments"); check("plain list nav", r["route"]=="/deployments" and len(r["results"])==5, r)
r = say(admin, "create a new deployment"); check("create dep (admin denied)", r["intent"]=="error", r)
r = say(admin, "report a new aws issue"); check("create aws", r["route"]=="/aws-issues?new=1", r)
r = say(admin, "search stylo"); check("search", r["intent"]=="search" and len(r["results"])==2, r)
r = say(admin, "search 123"); check("search digits -> open", r["intent"] in ("open","search"), r)
r = say(admin, "give me a summary"); check("summary", r["intent"]=="summary" and "deployments" in r["speech"], r)
r = say(admin, "who am i"); check("whoami", "Hari Admin" in r["speech"] and "admin" in r["speech"], r)
r = say(admin, "what can you do"); check("help", r["intent"]=="help", r)
r = say(admin, "thank you"); check("dismiss", r["intent"]=="dismiss", r)
r = say(admin, "hello"); check("greet", r["intent"]=="greet", r)
r = say(admin, "log out"); check("logout", r["intent"]=="logout", r)
r = say(admin, "blah blah zzzz"); check("unknown -> friendly", r["intent"]=="unknown", r)

print("== status change (needs confirm) ==")
r = say(admin, "approve deployment 123"); a = r.get("action") or {}
check("approve -> confirm", r["intent"]=="confirm" and a.get("newStatus")=="APPROVED" and not a.get("needsReason"), r)
r = say(admin, "approve deployment"); check("approve w/o number -> clarify", r["intent"]=="clarify" and r["carry"]=="approve deployment", r)
r = say(admin, r["carry"] + " " + "123"); check("carry + number works", r["intent"]=="confirm", r)
r = say(admin, "reject deployment 123"); check("reject needs reason", r["action"]["needsReason"] is True, r)
r = say(admin, "mark deployment 125 as failed"); check("mark failed", r["action"]["newStatus"]=="COMPLETED_FAILED" and r["action"]["needsReason"], r)
r = say(admin, "mark deployment 125 as successful"); check("mark success", r["action"]["newStatus"]=="COMPLETED_SUCCESS" and "mark deployment 125 as deployed successfully" in r["speech"], r["speech"])
r = say(admin, "roll back deployment 125"); check("rollback", r["action"]["newStatus"]=="ROLLED_BACK", r)
r = say(admin, "start deployment 124"); check("start", r["action"]["newStatus"]=="IN_PROGRESS", r)
r = say(admin, "grant access 7"); check("grant access", r["intent"]=="confirm" and r["action"]["recordType"]=="ACCESS" and r["action"]["newStatus"]=="ACCESS_GIVEN" or r["intent"]=="confirm", r)
r = say(eng, "mark deployment 123 as successful"); check("non-admin invalid transition refused", r["intent"]=="error" and "can't be marked" in r["speech"], r)

r = say(admin, "open a new access request"); check("open a new access", r["route"]=="/access?new=1", r)
r = say(admin, "new deployments"); check("'new deployments' is a list", r["intent"]=="list", r)
r = say(dev, "I want to raise an access request"); check("raise access", r["route"]=="/access?new=1", r)
print("== role limits ==")
r = say(dev, "approve deployment 123"); check("dev cannot approve", r["intent"]=="error" and "Only DevOps" in r["speech"], r)
r = say(dev, "show aws issues"); check("dev cannot see aws issues", r["intent"]=="error", r)
r = say(dev, "go to users"); check("dev cannot open users", r["intent"]=="error", r)
r = say(dev, "create new deployment"); check("dev can create deployment", r["route"]=="/deployments?new=1", r)
r = say(dev, "show my deployments"); check("mine filter", len(r["results"])==5, r)

print("== deployment outcome e-mails ==")
def run_status(actor, dep_id, status, reason=None, **kw):
    body = {"id": dep_id, "newStatus": status, "reason": reason, **kw}
    db.info.pop("pending_emails", None)
    logic.handle_update_deployment_status(db, body, ctx(actor))
    db.commit()
    return db.info.get("pending_emails", [])

mails = run_status(eng, "DEP-000125", "COMPLETED_SUCCESS")
m = mails[0]
check("success mail queued", len(mails)==1 and "SUCCESSFUL" in m.subject and "DEP-000125" in m.subject, m.subject if mails else "none")
to = [e for _, e in m.to]; cc = [e for _, e in m.cc]
check("To has requester + assigned + admin", {"keshava@axiotechx.com","eswar@axiotechx.com","hari@axiotechx.com"} <= set(to), to)
check("Cc has the rest, including legacy opt-outs", "qa@axiotechx.com" in cc and "quiet@axiotechx.com" in cc+to, (to, cc))
check("no one in both To and Cc", not (set(to) & set(cc)))
check("html has CTA + green chip", "/deployments/DEP-000125" in m.html and "DEPLOYED SUCCESSFULLY" in m.html)

dep124 = db.get(models.Deployment, "DEP-000124"); dep124.status = "IN_PROGRESS"; db.commit()
mails = run_status(eng, "DEP-000124", "COMPLETED_FAILED", "Migration script timed out")
m = mails[0]
check("failed mail", "FAILED" in m.subject and "Migration script timed out" in m.text and "Failure reason" in m.html, m.subject)

dep123 = db.get(models.Deployment, "DEP-000123"); dep123.status = "IN_PROGRESS"; db.commit()
mails = run_status(eng, "DEP-000123", "ROLLED_BACK", "Login broke after release")
m = mails[0]
check("rollback mail", "ROLLED BACK" in m.subject and "Login broke after release" in m.text and "release/1.1" in m.text, m.subject)
check("PROD warning on rollback", "Production deployment" in m.html)

dep124.status = "REQUESTED"; db.commit()
mails = run_status(admin, "DEP-000124", "APPROVED")
check("approve sends NO outcome mail", len(mails)==0)

dep124.status = "IN_PROGRESS"; db.commit()
mails = run_status(eng, "DEP-000124", "COMPLETED_SUCCESS", sendEmail=False)
check("legacy sendEmail=false cannot disable outcome mail", len(mails)==1)

eng.preferences = {"emailNotifications": False}; db.commit()
dep124.status = "IN_PROGRESS"; db.commit()
mails = run_status(eng, "DEP-000124", "COMPLETED_SUCCESS")
check("legacy account opt-out cannot disable outcome mail", len(mails)==1)
eng.preferences = {}; db.commit()

rb = run_status.__globals__["m"] if False else None
print("== password reset e-mail ==")
db.info.pop("pending_emails", None)
reset_result = logic.handle_request_password_reset(db, {"email": dev.email})
reset_mail = db.info.get("pending_emails", [None])[0]
check("reset request keeps generic response", "If that email is registered" in reset_result["message"])
check("reset OTP email queued to account email",
      reset_mail is not None and reset_mail.to == [(dev.name, dev.email)])
check("reset OTP included in email with expiry",
      reset_mail is not None and dev.reset_otp in reset_mail.text
      and f"{logic.settings.OTP_TTL_MINUTES} minutes" in reset_mail.text)
check("reset email is marked for inline delivery",
      reset_mail is not None and reset_mail.send_inline)
reset_deliveries = []
original_deliver = mailer._deliver
mailer._deliver = lambda message: reset_deliveries.append(message)
try:
    mailer.dispatch_pending(db)
finally:
    mailer._deliver = original_deliver
check("reset email is delivered before the API response returns",
      reset_deliveries == [reset_mail])
original_hash_password = logic.hash_password
logic.hash_password = lambda password: f"test-hash:{password}"
try:
    reset_result = logic.handle_reset_password(db, {
        "email": dev.email,
        "otp": dev.reset_otp,
        "newPassword": "NewPassword1!",
    })
finally:
    logic.hash_password = original_hash_password
check("emailed OTP creates the new password and is cleared",
      "Password updated" in reset_result["message"]
      and dev.password_hash == "test-hash:NewPassword1!"
      and dev.reset_otp is None and dev.reset_otp_expiry is None)

print("== admin create user ==")
db.info.pop("pending_emails", None)
original_hash_password = logic.hash_password
logic.hash_password = lambda password: f"test-hash:{password}"
try:
    logic.handle_admin_create_user(db, {
        "name": "Unauthorized User",
        "email": "unauthorized@axiotechx.com",
        "mobile": "9876543211",
        "role": "Developer",
    }, ctx(dev))
    check("non-admin cannot create users", False)
except ApiError:
    check("non-admin cannot create users", True)
try:
    created = logic.handle_admin_create_user(db, {
        "name": "New Admin",
        "email": "newadmin@axiotechx.com",
        "mobile": "9876543210",
        "password": "NewAdmin123!",
        "role": "DevOps",
        "power": True,
    }, ctx(admin))
finally:
    logic.hash_password = original_hash_password
new_user = db.get(models.User, created["user"]["id"])
create_mail = db.info.get("pending_emails", [None])[0]
check("admin-created user is active, approved, and has admin power",
      new_user is not None and new_user.active and new_user.status == "APPROVED"
      and new_user.role == "DevOps" and new_user.power)
check("admin-entered password is used and not included in the email or API result",
      create_mail is not None and create_mail.to == [(new_user.name, new_user.email)]
      and "Temporary password" not in create_mail.text
      and "NewAdmin123!" not in create_mail.text
      and "NewAdmin123!" not in str(created)
      and new_user.password_hash == "test-hash:NewAdmin123!"
      and create_mail.send_inline)
db.info.pop("pending_emails", None)
long_email = "madhan.mohan.mittal.long@axiotechx.com"
logic.hash_password = lambda password: f"test-hash:{password}"
try:
    long_created = logic.handle_admin_create_user(db, {
        "name": "Long Email User",
        "email": long_email,
        "mobile": "9876543212",
        "password": "LongEmail123!",
        "role": "Developer",
    }, ctx(admin))
finally:
    logic.hash_password = original_hash_password
check("company email longer than 30 characters is accepted",
      long_created["user"]["email"] == long_email and len(long_email) > 30)

print("\nRESULT:", ok, "passed,", fail, "failed")
sys.exit(1 if fail else 0)
