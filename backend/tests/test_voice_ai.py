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
    if cond:
        ok += 1; print("  PASS", label)
    else:
        fail += 1; print("  FAIL", label, extra)

def ask(u, text, context=None, history=None):
    return voice.handle_voice_command(db, {"text": text, "context": context or {}, "history": history or []}, ctx(u))

print("== context: 'it' / 'this one' ==")
page = {"route": "/deployments/DEP-000123", "recordId": "DEP-000123"}
r = ask(admin, "approve it", page); a = r.get("action") or {}
check("approve it -> current record", r["intent"] == "confirm" and a.get("id") == "DEP-000123" and a.get("newStatus") == "APPROVED", r)
r = ask(admin, "reject this one", page); check("reject this one -> needs reason", r["action"]["id"] == "DEP-000123" and r["action"]["needsReason"], r)
r = ask(admin, "approve deployment", {"lastRecordId": "DEP-000123"}); check("last record talked about", r["intent"] == "confirm", r)
r = ask(admin, "approve it", {"recordId": "ACC-000007"}); check("approve access on access page", r["action"]["recordType"] == "ACCESS", r)
r = ask(admin, "grant it", page); check("grant on a deployment page -> clarify", r["intent"] == "clarify", r)
r = ask(admin, "open it", {"results": ["DEP-000124"]}); check("open it -> the only result", r["route"] == "/deployments/DEP-000124", r)
r = ask(admin, "approve it"); check("no context -> clarify", r["intent"] == "clarify", r)
r = ask(admin, "show failed deployments", page); check("lists unaffected by context", r["intent"] == "list" and len(r["results"]) == 2, r)
r = ask(admin, "is there any failed deployment", page); check("'any' question is not about the page record", r["intent"] != "answer", r)

print("== questions about a record ==")
r = ask(admin, "who requested deployment 123"); check("who requested", r["intent"] == "answer" and "Keshava Dev" in r["speech"], r["speech"])
r = ask(admin, "who is assigned to deployment 123"); check("who is assigned", "Eswar DevOps" in r["speech"], r["speech"])
r = ask(admin, "what's the status of it", page); check("status of it", "requested" in r["speech"].lower(), r["speech"])
r = ask(admin, "when is it scheduled", page); check("when", "scheduled" in r["speech"], r["speech"])
r = ask(admin, "which branch is deployment 123"); check("branch", "release/1.2" in r["speech"] and "release/1.1" in r["speech"], r["speech"])
r = ask(admin, "tell me about deployment 125"); check("describe", "in progress" in r["speech"].lower() and "PG-Desk" in r["speech"], r["speech"])
r = ask(admin, "is deployment 124 approved"); check("yes/no status", "approved" in r["speech"].lower(), r["speech"])
r = ask(admin, "who requested deployment 999"); check("missing record", r["intent"] == "error", r)
check("answer remembers focus", r.get("focus") is None and ask(admin, "who requested deployment 123").get("focus") == "DEP-000123")
r = ask(dev, "what is the status of aws issue 2"); check("dev cannot read aws issue", r["intent"] == "error", r)

print("== edits & reassignment ==")
r = ask(eng, "set the rollback branch of deployment 124 to release slash 1.0"); a = r.get("action") or {}
check("edit rollback branch", r["intent"] == "confirm" and a.get("kind") == "edit" and a["fields"] == {"rollbackBranch": "release/1.0"}, r)
r = ask(eng, "Hello Ops, change the rollback branch to hotfix/2.3.1", page)
check("edit current record keeps dots", r["action"]["fields"]["rollbackBranch"] == "hotfix/2.3.1" and r["action"]["id"] == "DEP-000123", r)
r = ask(dev, "set the rollback branch of deployment 124 to main"); check("dev cannot edit", r["intent"] == "error", r)
r = ask(admin, "assign deployment 123 to eswar"); a = r.get("action") or {}
check("assign by first name", r["intent"] == "confirm" and a.get("kind") == "reassign" and a.get("newDevOpsId") == "USR-2", r)
r = ask(admin, "assign it to me", page); check("assign to me", r["action"]["newDevOpsId"] == "USR-1", r)
r = ask(admin, "assign deployment 123 to nobodyxyz"); check("unknown person -> clarify with names", r["intent"] == "clarify" and "Eswar" in r["speech"], r)
r = ask(eng, "assign deployment 123 to eswar"); check("non-admin cannot assign", r["intent"] == "error", r)
r = ask(dev, "give me access to rds"); check("'give me access' is still create access", r["route"] == "/access?new=1", r)

print("== AI agent (Claude mocked) ==")
from app import llm
calls = []
script = []
def fake_call(body, timeout=7.0):
    calls.append(body)
    return script.pop(0) if script else None
llm.call = fake_call
llm.enabled = lambda: True
llm.model = lambda: "test-model"
def tool(name, inp, i="t1"):
    return {"content": [{"type": "tool_use", "id": i, "name": name, "input": inp}]}

script[:] = [tool("find_records", {"kind": "DEPLOYMENT", "project": "PG-Desk", "status": "COMPLETED_FAILED"}),
             tool("answer", {"text": "PG-Desk had 1 failed deployment, number 127.", "record_ids": ["DEP-000127"]}, "t2")]
r = ask(admin, "did anything go wrong with the pg desk releases recently hmm")
check("agent looks up then answers", r["source"] == "ai" and r["intent"] == "answer" and r["results"][0]["id"] == "DEP-000127", r)
tr = calls[-1]["messages"][-1]["content"][0]
check("look-up result fed back to the model", tr["type"] == "tool_result" and '"count": 1' in tr["content"], tr)
check("no secrets sent", "DBChangeFileData" not in json.dumps(calls[-1]) and "EnvVarDetails" not in json.dumps(calls[-1]))

calls.clear()
script[:] = [tool("change_status", {"record": "DEP-000123", "new_status": "APPROVED"})]
r = ask(admin, "yeah go ahead and okay the stylo customer one", history=[
    {"role": "user", "text": "show pending deployments"}, {"role": "assistant", "text": "I found 1 pending deployment."}])
check("agent action -> normal confirm", r["intent"] == "confirm" and r["action"]["id"] == "DEP-000123", r)
check("conversation memory sent", [m["role"] for m in calls[0]["messages"]] == ["user", "assistant", "user"], calls[0]["messages"])

script[:] = [tool("change_status", {"record": "123", "new_status": "APPROVED"})]
r = ask(dev, "please just approve one two three for me right now")
check("agent cannot bypass permissions", r["intent"] == "error" and "Only DevOps" in r["speech"], r)

script[:] = [tool("show_records", {"kind": "DEPLOYMENT", "requested_by": "keshava", "environment": "PROD"})]
r = ask(admin, "what has keshava been pushing to production lately")
check("agent filter by person", r["intent"] == "list" and len(r["results"]) == 3 and "raised by keshava" in r["speech"], r["speech"])

script[:] = []
r = ask(admin, "blah blah zzzz")
check("AI down -> rules fallback still answers", r["intent"] == "unknown" and r["source"] == "rules", r)

calls.clear()
r = ask(admin, "open deployment 123")
check("simple commands never wait for the AI", not calls and r["source"] == "rules")
check("simple command is fast", r["ms"] < 200, r["ms"])

print(f"\nRESULT: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
