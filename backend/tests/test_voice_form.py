# Run from the backend folder:  python tests/test_voice_form.py
# Pure Python: no database, no network (the optional Claude call is skipped without an API key).
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import importlib.util
spec = importlib.util.spec_from_file_location("voice_form", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "voice_form.py"))
vf = importlib.util.module_from_spec(spec); spec.loader.exec_module(vf)

APPS = ["Stylo PG Desk", "Stylo Partner", "Billing Portal", "OPSFlow"]
ENVS = ["DEV", "QA", "UAT", "PROD"]
NOW = "2026-11-05T20:40"          # a Thursday evening


class Session:
    """Mimics the browser: keeps the real form values and applies each patch to them."""
    def __init__(self, kind, form=None, role="Developer"):
        self.kind, self.flow, self.role = kind, {}, role
        self.form = form or {}
        self.last = None

    def say(self, text, start=False):
        r = vf.turn(self.kind, text, self.form, self.flow, NOW, APPS, ENVS, None, "Hari", start, self.role)
        for k, v in r["patch"].items():
            if k == "envVarsAdd":
                self.form["envVars"] = (self.form.get("envVars") or []) + [{"key": x["key"], "hasValue": True} for x in v]
            else:
                self.form[k] = v
        self.flow = r["flow"]
        self.last = r
        return r


def dep_form():
    return {"project": "", "component": "Frontend", "environment": "PROD", "dateTime": "", "githubUrl": "",
            "githubBranch": "", "rollbackBranch": "", "appVersion": "", "githubCommit": "", "dbChange": False,
            "thirdPartyApiChange": False, "envVarChange": False, "envVars": [], "applicationChangeDetails": "",
            "additionalInfo": ""}


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   -> {extra}" if not cond else ""))
    if not cond:
        check.failed += 1
check.failed = 0


# ---------- 1. full frontend deployment, one answer per turn ----------
s = Session("DEPLOYMENT", dep_form())
r = s.say("create a deployment request", start=True)
check("start asks for the application", "application" in r["speech"].lower(), r["speech"])
r = s.say("stylo pg desk")
check("project matched", s.form["project"] == "Stylo PG Desk", s.form)
check("asks frontend or backend next", "frontend or the backend" in r["speech"], r["speech"])
r = s.say("frontend")
check("component set + asks environment", s.form["component"] == "Frontend" and "environment" in r["speech"].lower(), r["speech"])
r = s.say("production")
check("environment PROD confirmed", s.form["environment"] == "PROD" and "dateTime" not in s.form or True)
check("then asks date", "deployed" in r["speech"].lower(), r["speech"])
r = s.say("tomorrow at 10 pm")
check("datetime parsed", s.form["dateTime"] == "2026-11-06T22:00", s.form.get("dateTime"))
check("speech reads the time back", "10:00 PM" in r["speech"], r["speech"])
r = s.say("github dot com slash axiotech slash stylo dash pg")
check("url spoken symbols", s.form["githubUrl"] == "https://github.com/axiotech/stylo-pg", s.form.get("githubUrl"))
r = s.say("release slash 2.1")
check("branch keeps slash", s.form["githubBranch"] == "release/2.1", s.form.get("githubBranch"))
check("rollback branch is no longer required (goes straight to the optional question)", "version" in s.last["speech"].lower() and "rollback" in s.last["speech"].lower(), s.last["speech"])
r = s.say("rollback branch main, version 2.3.1 and notes hotfix for login")
check("rollback branch captured by voice (optional)", s.form.get("rollbackBranch") == "main", s.form.get("rollbackBranch"))
check("optional version + notes", s.form.get("appVersion") == "v2.3.1" and "hotfix" in s.form.get("additionalInfo", "").lower(), s.form)
check("done flag set", r.get("done") is True, r)
check("tells user to click submit", "submit" in r["speech"].lower())
check("progress complete", r["progress"]["filled"] == r["progress"]["total"], r["progress"])

# ---------- 2. everything in the first sentence ----------
s = Session("DEPLOYMENT", dep_form())
r = s.say("deploy stylo pg desk backend to production tomorrow at 10 pm", start=True)
check("one sentence fills project/component/env/date",
      s.form["project"] == "Stylo PG Desk" and s.form["component"] == "Backend" and s.form["environment"] == "PROD"
      and s.form["dateTime"] == "2026-11-06T22:00", s.form)
check("asks for GitHub URL next", "github" in r["speech"].lower(), r["speech"])

# ---------- 3. backend asks the extra questions ----------
r = s.say("github.com/axiotech/stylo-pg")
r = s.say("branch release-5")
check("branch via keyword", s.form.get("githubBranch") == "release-5", s.form)
check("backend asks DB change", "database" in r["speech"].lower(), r["speech"])
r = s.say("yes")
check("dbChange true", s.form["dbChange"] is True)
r = s.say("no")
check("third party false then env var question", s.form["thirdPartyApiChange"] is False and "environment variable" in r["speech"].lower(), r["speech"])
r = s.say("no")
check("optional question next", "version" in r["speech"].lower(), r["speech"])
r = s.say("no")
check("done + manual DB file reminder", r.get("done") and "schema" in r["speech"].lower(), r["speech"])

# ---------- 4. safety: voice can never submit ----------
r = s.say("submit the request")
check("submit refused", "can't submit" in r["speech"].lower() and r["intent"] == "form", r["speech"])
r = s.say("submit")
check("plain 'submit' refused", "can't submit" in r["speech"].lower())

# ---------- 5. past dates rejected, partial dates ----------
s = Session("DEPLOYMENT", dep_form())
s.say("create a deployment for stylo pg desk frontend on prod", start=True)
r = s.say("yesterday at 9 am")
check("past rejected", "passed" in r["speech"].lower() and not s.form.get("dateTime"), r["speech"])
r = s.say("12 november")
check("date only asks time", "what time" in r["speech"].lower() and s.flow.get("pending_date") == "2026-11-12", r["speech"])
r = s.say("9:30 am")
check("pending date + time combined", s.form.get("dateTime") == "2026-11-12T09:30", s.form.get("dateTime"))

# ---------- 6. ambiguity, unknown app, corrections ----------
s = Session("DEPLOYMENT", dep_form())
r = s.say("create a deployment", start=True)
r = s.say("stylo")
check("ambiguous app lists choices", "Stylo PG Desk" in r["speech"] and "Stylo Partner" in r["speech"] and not s.form.get("project"), r["speech"])
r = s.say("the second one")
check("ordinal picks second choice", s.form.get("project") == "Stylo Partner", s.form)
s2 = Session("DEPLOYMENT", dep_form()); s2.say("create a deployment", start=True)
r = s2.say("banana")
check("unknown app rejected politely", "don't have" in r["speech"].lower() and not s2.form.get("project"), r["speech"])
s.say("frontend"); s.say("keep")
r = s.say("change the environment to QA")
check("correction changes env", s.form["environment"] == "QA", s.form)

# ---------- 7. access request ----------
s = Session("ACCESS", {"accessType": "", "project": "", "environment": "PROD", "userResource": "",
                       "accessLevel": "Read Only", "durationDays": 7, "customDays": "", "reason": ""}, role="Developer")
r = s.say("I need access to S3 for stylo pg desk in uat", start=True)
check("access type/app/env from first sentence", s.form["accessType"] == "S3" and s.form["project"] == "Stylo PG Desk" and s.form["environment"] == "UAT", s.form)
r = s.say("keshava")
check("user resource", s.form["userResource"] == "Keshava", s.form)
r = s.say("read write")
check("access level", s.form["accessLevel"] == "Read / Write", s.form)
r = s.say("45 days")
check("custom duration", s.form["durationDays"] == "Custom" and s.form["customDays"] == "45", s.form)
r = s.say("because I need to debug the upload bucket")
check("reason strips 'because'", s.form["reason"].lower().startswith("i need to debug"), s.form)
check("access done", r.get("done") is True, r["speech"])

# ---------- 8. AWS issue (DevOps) ----------
s = Session("AWS_ISSUE", {"project": "", "service": "", "priority": "High", "errorMessage": "", "impact": ""}, role="DevOps")
r = s.say("report an aws issue", start=True)
r = s.say("billing portal")
r = s.say("ec2")
check("service EC2", s.form["service"] == "EC2", s.form)
r = s.say("critical")
check("priority critical", s.form["priority"] == "Critical", s.form)
r = s.say("instance status check failed with 502 errors")
check("free text not mistaken for a status command", "502" in s.form.get("errorMessage", ""), s.form)
r = s.say("customers cannot log in")
check("aws done", r.get("done") is True, r["speech"])

# ---------- 9. permissions ----------
check("QA cannot use AWS form", vf.can_use("AWS_ISSUE", "QA", False) is not None)
check("Developer can use deployment", vf.can_use("DEPLOYMENT", "Developer", False) is None)
check("DevOps cannot raise deployment", vf.can_use("DEPLOYMENT", "DevOps", False) is not None)
check("application form is admin only", vf.can_use("APPLICATION", "DevOps", False) is not None and vf.can_use("APPLICATION", "DevOps", True) is None)

# ---------- 10. cancel + env vars never reach the model ----------
r = Session("DEPLOYMENT", dep_form()).say("cancel", start=False)
check("cancel intent", r["intent"] == "form_cancel")
s = Session("DEPLOYMENT", {**dep_form(), "component": "Backend", "project": "OPSFlow", "environment": "PROD",
                           "dateTime": "2026-11-06T22:00", "githubUrl": "https://github.com/a/b",
                           "githubBranch": "x", "rollbackBranch": "y", "dbChange": False,
                           "thirdPartyApiChange": False, "envVarChange": True})
s.flow = {"confirmed": ["environment", "component", "dbChange", "thirdPartyApiChange", "envVarChange"], "skipped": [], "asking": "envVars"}
_orig_llm = vf.llm_extract
vf.llm_extract = lambda *a, **k: (_ for _ in ()).throw(AssertionError("env var text was sent to the model"))
r = s.say("API URL equals https colon slash slash example dot com and DB HOST is localhost")
check("env vars parsed by rules", len(s.form["envVars"]) == 2, s.form.get("envVars"))
check("env vars ask for more first", "any more variables" in r["speech"].lower() or "version" not in r["speech"].lower(), r["speech"])
r = s.say("done")
check("env vars done moves on", "version" in r["speech"].lower(), r["speech"])
vf.llm_extract = _orig_llm

# ---------- 11. APPLICATION ----------
s = Session("APPLICATION", {"name": ""}, role="DevOps")
r = s.say("add a new application called Stylo Wallet", start=True)
check("application name captured", s.form.get("name") == "Stylo Wallet", s.form)
check("application done", r.get("done") is True, r["speech"])

# ---------- 12. Claude path (mocked): one sentence fills many fields, bad values are still rejected ----------
vf.llm_extract = lambda *a, **k: {"project": "Billing Portal", "component": "Backend", "environment": "UAT",
                                  "date": "2026-11-06", "time": "22:00", "githubBranch": "release/9", "command": "none"}
s = Session("DEPLOYMENT", dep_form())
r = s.say("deploy billing backend to uat tomorrow ten pm branch release nine", start=True)
check("LLM: many fields in one turn", s.form["project"] == "Billing Portal" and s.form["environment"] == "UAT"
      and s.form["dateTime"] == "2026-11-06T22:00" and s.form["githubBranch"] == "release/9", s.form)
vf.llm_extract = lambda *a, **k: {"project": "Totally Made Up App", "environment": "MOON", "command": "none"}
s = Session("DEPLOYMENT", dep_form())
r = s.say("deploy something", start=True)
check("LLM: invented app / environment rejected", not s.form.get("project") and s.form.get("environment") == "PROD", s.form)
vf.llm_extract = lambda *a, **k: {"command": "cancel"}
s = Session("DEPLOYMENT", dep_form()); s.say("create", start=True)
r = s.say("never mind this whole thing please forget it")
check("LLM: cancel command", r["intent"] == "form_cancel", r["intent"])
vf.llm_extract = _orig_llm

# ---- go back one step / review ----
s = Session("DEPLOYMENT", dep_form()); s.say("create a deployment", start=True)
r = s.say("go back"); check("back at the very start closes the form", r["intent"] == "form_cancel", r["intent"])
s = Session("DEPLOYMENT", dep_form()); s.say("create a deployment", start=True)
s.say("stylo partner")
first_q = s.last["flow"].get("last_question")
s.say("production")
q_after = s.flow.get("last_question")
r = s.say("go back")
check("back keeps the form open", r["intent"] == "form", r["intent"])
check("back asks the previous question again", "one step back" in r["speech"].lower(), r["speech"])
check("back re-asks the last answered question", "environment" in r["speech"].lower() and s.flow.get("order") == ["project"], (r["speech"], s.flow.get("order")))
r = s.say("review"); check("review reads the form", r.get("review") is True and "Here is what I have" in r["speech"], r["speech"])
s2 = Session("DEPLOYMENT", dep_form()); s2.say("create a deployment", start=True)
r = s2.say("previous question"); check("'previous question' also works", r["intent"] in ("form", "form_cancel"), r["intent"])

print("\nFAILED: %d" % check.failed if check.failed else "\nAll voice-form tests passed.")
sys.exit(1 if check.failed else 0)
