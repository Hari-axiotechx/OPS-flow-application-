"""
Guided, spoken form filling for the OPSFlow voice assistant  (action: voiceForm).

The user says "Hello Ops, create a deployment". The browser opens the real form and
then, turn by turn, sends what the user said plus the CURRENT values of the form.
This module answers with
    patch     -> values the UI writes into the visible form fields
    speech    -> what the assistant says next (an acknowledgement + the next question)
    progress  -> checklist shown in the assistant panel
    flow      -> small state object the browser sends back on the next turn
                 (the server keeps no state)
    done      -> every required field is filled

NOTHING HERE SUBMITS A REQUEST. The only thing that can create a record is the user
clicking "Submit Request" on the form. Asking to "submit" gets a polite refusal.

Understanding the speech
  1. If ANTHROPIC_API_KEY is set, Claude extracts any number of fields from one
     sentence ("deploy stylo backend to prod tomorrow 10 pm, branch release/2.1")
     through a single tool call. Secrets (env-var values, uploaded files) are never
     sent to the model.
  2. Without a key, or if the call fails, a rule-based parser is used.
  Either way every value is re-validated here (applications / environments must exist,
  dates must parse and not be in the past, URLs must look like URLs ...), so the model
  can only ever suggest values, never bypass a rule.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import date, datetime, timedelta

log = logging.getLogger("opsflow.voice.form")

# ----------------------------------------------------------------------
# Static option lists (kept in sync with the React forms)
# ----------------------------------------------------------------------
ACCESS_TYPES = ["AWS", "S3", "RDS", "IAM", "Database", "Server / EC2", "Kubernetes", "CI/CD",
                "Application", "Monitoring", "Cloud Console", "Other"]
ACCESS_LEVELS = ["Read Only", "Read / Write", "Full Access", "Custom"]
DURATIONS = [1, 3, 7, 15, 30, 60, 90]
COMPONENTS = ["Frontend", "Backend"]
DEFAULT_PRIORITIES = ["Low", "Medium", "High", "Critical"]
AWS_SERVICES = [
    "EC2", "S3", "RDS", "Lambda", "VPC", "IAM", "CloudFront", "Route 53", "ECS", "EKS", "DynamoDB",
    "CloudWatch", "SNS", "SQS", "API Gateway", "Elastic Beanstalk", "ELB / ALB", "EBS", "CloudFormation",
    "KMS", "Secrets Manager", "ElastiCache", "Redshift", "Kinesis", "Step Functions", "SES", "WAF", "ACM",
    "CodePipeline", "CodeBuild", "CodeDeploy", "Auto Scaling", "Elastic IP", "NAT Gateway", "EFS", "Athena",
    "Glue", "CloudTrail", "Systems Manager", "Other",
]

OPTIONAL_KEY = "__optional__"   # flow.asking value while the "anything else?" question is open


def _backend(f: dict) -> bool:
    return f.get("component") == "Backend"


def F(key, label, kind, ask, **kw):
    return {"key": key, "label": label, "kind": kind, "ask": ask, "required": kw.pop("required", True), **kw}


FORMS: dict[str, dict] = {
    "DEPLOYMENT": {
        "title": "deployment request",
        "roles": ("Developer", "QA"),
        "role_msg": "Only Developers and QA can raise deployment requests.",
        "fields": [
            F("project", "Application", "enum", "Which application is this deployment for?", options="apps"),
            F("component", "Frontend or backend", "enum", "Is it the frontend or the backend?",
              options="components", default="Frontend"),
            F("environment", "Environment", "enum", "Which environment: {options}?", options="envs", default="PROD"),
            F("dateTime", "Date and time", "datetime", "When should it be deployed? For example, tomorrow at 10 PM."),
            F("githubUrl", "GitHub URL", "url", "What is the GitHub repository URL?"),
            F("githubBranch", "Branch", "token", "Which branch are we deploying?"),
            F("dbChange", "DB or schema change", "bool", "Is there a database or schema change?",
              default=False, when=_backend),
            F("thirdPartyApiChange", "Third-party API change", "bool", "Is there a third-party API change?",
              default=False, when=_backend),
            F("thirdPartyApiDetails", "Third-party API details", "text",
              "Which third-party APIs are affected, and how?",
              when=lambda f: _backend(f) and f.get("thirdPartyApiChange") is True),
            F("envVarChange", "Environment variable change", "bool", "Are there any environment variable changes?",
              default=False, when=_backend),
            F("envVars", "Environment variables", "envvars",
              "Tell me each variable like: NAME equals value. For secrets it is safer to type them in the form or "
              "upload a .env file. Say done when finished, or say I will type them.",
              when=lambda f: _backend(f) and f.get("envVarChange") is True),
        ],
        "optional": [
            F("rollbackBranch", "Rollback branch", "token", "", required=False),
            F("appVersion", "Version", "token", "", required=False),
            F("githubCommit", "Commit ID", "commit", "", required=False),
            F("applicationChangeDetails", "Change details", "text", "", required=False),
            F("additionalInfo", "Additional information", "text", "", required=False),
        ],
        "optional_ask": "Would you like to add a rollback branch, version, commit ID, change details or any notes? "
                        "Say what to add, or say no to skip.",
    },
    "ACCESS": {
        "title": "access request",
        "roles": None,
        "fields": [
            F("accessType", "Access type", "enum", "What type of access do you need: AWS, S3, RDS, IAM, Database, "
              "Server, Kubernetes, CI CD, Application, Monitoring, Cloud Console or Other?", options="access_types"),
            F("project", "Application", "enum", "Which application is it for?", options="apps"),
            F("environment", "Environment", "enum", "Which environment: {options}?", options="envs", default="PROD"),
            F("userResource", "User or resource", "text", "Who or which resource needs the access?"),
            F("accessLevel", "Access level", "enum", "What access level: Read Only, Read Write, Full Access or Custom?",
              options="access_levels", default="Read Only"),
            F("customAccessLevel", "Custom access", "text", "Describe the custom access you need.",
              when=lambda f: f.get("accessLevel") == "Custom"),
            F("durationDays", "Duration", "duration", "For how many days do you need it?", default=7),
            F("customDays", "Number of days", "int", "How many days exactly?",
              when=lambda f: f.get("durationDays") == "Custom"),
            F("reason", "Reason", "text", "What is the reason for the request?"),
        ],
        "optional": [],
        "optional_ask": "",
    },
    "AWS_ISSUE": {
        "title": "AWS issue",
        "roles": ("DevOps",),
        "role_msg": "Only DevOps users can report AWS issues.",
        "fields": [
            F("project", "Application", "enum", "Which application is affected?", options="apps"),
            F("service", "AWS service", "service", "Which AWS service is the issue in?"),
            F("priority", "Priority", "enum", "What is the priority: Low, Medium, High or Critical?",
              options="priorities", default="High"),
            F("errorMessage", "Error message", "text", "What is the error or message?"),
            F("impact", "Impact", "text", "What is the impact?"),
        ],
        "optional": [],
        "optional_ask": "",
    },
    "APPLICATION": {
        "title": "new application",
        "roles": None,
        "admin_only": True,
        "role_msg": "Only DevOps admins can add applications.",
        "fields": [F("name", "Application name", "text", "What is the name of the new application?")],
        "optional": [],
        "optional_ask": "",
    },
}

# Words that point at a field in "change the <word> to <value>"
FIELD_WORDS = {
    "project": r"project|app|application",
    "component": r"component|frontend|backend|front end|back end",
    "environment": r"environment|env",
    "dateTime": r"date|time|date and time|schedule|when",
    "githubUrl": r"url|repo|repository|github url|link",
    "rollbackBranch": r"rollback branch|roll back branch|rollback",
    "githubBranch": r"branch|github branch",
    "appVersion": r"version",
    "githubCommit": r"commit|commit id",
    "applicationChangeDetails": r"change details|application change details|changes",
    "additionalInfo": r"notes?|additional info(?:rmation)?|comments?",
    "accessType": r"access type|type",
    "userResource": r"user|resource|user or resource",
    "accessLevel": r"access level|level|permission",
    "durationDays": r"duration|days",
    "reason": r"reason",
    "service": r"service",
    "priority": r"priority",
    "errorMessage": r"error(?: message)?|message",
    "impact": r"impact",
    "name": r"name|application name",
    "thirdPartyApiDetails": r"third party api details|api details",
}

# ----------------------------------------------------------------------
# Small text helpers
# ----------------------------------------------------------------------
_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90,
}
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"]
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm(text: str) -> str:
    t = str(text or "").lower().replace("&", " and ")
    t = re.sub(r"[^\w\s'/:\-.@]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def squash(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _words_to_digits(t: str) -> str:
    """'ten thirty' -> '10 30', 'twenty five' -> '25'. Only used for times / days."""
    toks, out, i = t.split(), [], 0
    while i < len(toks):
        w = toks[i]
        if w in _NUM_WORDS:
            n = _NUM_WORDS[w]
            if n >= 20 and n % 10 == 0 and i + 1 < len(toks) and toks[i + 1] in _NUM_WORDS and 1 <= _NUM_WORDS[toks[i + 1]] <= 9:
                n += _NUM_WORDS[toks[i + 1]]
                i += 1
            out.append(str(n))
        else:
            out.append(w)
        i += 1
    return " ".join(out)


def sentence(text: str) -> str:
    t = clean(text)
    return t[:1].upper() + t[1:] if t else t


def spoken_symbols(text: str) -> str:
    """'github dot com slash foo dash bar' -> 'github.com/foo-bar'."""
    t = " " + clean(text) + " "
    for word, sym in ((" dot ", "."), (" slash ", "/"), (" forward slash ", "/"), (" dash ", "-"), (" hyphen ", "-"),
                      (" underscore ", "_"), (" colon ", ":"), (" at the rate ", "@"), (" point ", ".")):
        t = re.sub(re.escape(word), sym, t, flags=re.I)
        t = re.sub(re.escape(word), sym, t, flags=re.I)  # overlapping matches ("a dot dot b")
    t = re.sub(r"\s*([./:_@])\s*", r"\1", t)
    t = re.sub(r"\s*-\s*", "-", t)
    return t.strip()


def parse_bool(text: str):
    t = norm(text)
    if re.match(r"^(?:yes|yeah|yep|yup|sure|correct|true|affirmative|there is|there are|it has|it does|definitely|of course)\b", t):
        return True
    if re.match(r"^(?:no|nope|nah|none|nothing|negative|false|not really|there is no|there are no|no change|without|n/a)\b", t):
        return False
    if re.search(r"\b(?:no changes?|nothing changed|not changing|none)\b", t):
        return False
    return None


# ----------------------------------------------------------------------
# Context + option matching
# ----------------------------------------------------------------------
class C:
    """Everything a coercion needs (no database access: the caller passes it in)."""

    def __init__(self, apps, envs, priorities, now, flow, role=""):
        self.apps = list(apps or [])
        self.envs = [e for e in (envs or []) if e] or ["DEV", "QA", "UAT", "PROD"]
        self.priorities = list(priorities or DEFAULT_PRIORITIES)
        self.now = now
        self.flow = flow
        self.role = role

    def options(self, name: str) -> list[str]:
        return {"apps": self.apps, "envs": self.envs, "components": COMPONENTS, "access_types": ACCESS_TYPES,
                "access_levels": ACCESS_LEVELS, "priorities": self.priorities}[name]


SYNONYMS = {
    "environment": {"DEV": ["development", "develop", "dev"], "PROD": ["production", "prod", "live"],
                    "QA": ["qa", "testing", "test", "quality"], "UAT": ["uat", "staging", "stage"]},
    "component": {"Frontend": ["front end", "frontend", "ui", "client", "web"],
                  "Backend": ["back end", "backend", "api", "server", "service"]},
    "accessType": {"Server / EC2": ["ec2", "server", "servers", "ssh", "instance", "virtual machine"],
                   "Kubernetes": ["kubernetes", "k8s", "kubernates", "cluster", "eks"],
                   "CI/CD": ["ci cd", "cicd", "ci/cd", "pipeline", "jenkins", "github actions"],
                   "Cloud Console": ["console", "cloud console", "aws console"],
                   "Database": ["database", "db", "postgres", "mysql", "sql"],
                   "S3": ["s3", "s 3", "bucket", "buckets"], "RDS": ["rds"], "IAM": ["iam"],
                   "AWS": ["aws", "amazon web services"], "Monitoring": ["monitoring", "grafana", "datadog", "cloudwatch"],
                   "Application": ["application", "app"], "Other": ["other", "something else"]},
    "accessLevel": {"Read Only": ["read only", "readonly", "read-only", "view only", "view", "read"],
                    "Read / Write": ["read write", "read and write", "read/write", "read / write", "write", "edit", "modify"],
                    "Full Access": ["full access", "full", "admin", "administrator", "everything"],
                    "Custom": ["custom", "specific", "something specific"]},
    "priority": {"Critical": ["critical", "urgent", "p0", "p 0", "severe", "blocker"],
                 "High": ["high", "important", "p1", "p 1"], "Medium": ["medium", "normal", "moderate", "p2", "p 2"],
                 "Low": ["low", "minor", "p3", "p 3"]},
}
_ORD = {"first": 0, "1st": 0, "one": 0, "1": 0, "second": 1, "2nd": 1, "two": 1, "2": 1, "third": 2, "3rd": 2,
        "three": 2, "3": 2, "fourth": 3, "4th": 3, "four": 3, "4": 3, "fifth": 4, "5th": 4, "five": 4, "5": 4,
        "sixth": 5, "6th": 5, "six": 5, "6": 5}


def match_option(text: str, options: list[str], syn: dict | None = None, choices: list[str] | None = None):
    """-> ('ok', value) | ('ambiguous', [values]) | ('none', None)."""
    t = norm(text)
    if not t or not options:
        return "none", None
    # "the second one" after the assistant listed choices
    if choices:
        m = re.match(r"^(?:the |number |option )?(\w+)(?: one| option)?$", t)
        if m and m.group(1) in _ORD and _ORD[m.group(1)] < len(choices):
            return "ok", choices[_ORD[m.group(1)]]
    sq = squash(t)
    for o in options:  # exact
        if squash(o) == sq:
            return "ok", o
    # option name fully contained in what was said (longest wins)
    def _in(o: str) -> bool:
        so = squash(o)
        if len(so) <= 3:
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(o.lower())}(?![a-z0-9])", t))
        return so in sq
    inside = [o for o in options if len(squash(o)) >= 2 and _in(o)]
    if inside:
        best = max(inside, key=lambda o: len(squash(o)))
        if len(squash(best)) >= 3 or len(inside) == 1:
            return "ok", best
    if syn:
        padded = f" {t} "
        hits = [v for v, words in syn.items() if v in options and any(f" {w} " in padded for w in words)]
        if len(hits) == 1:
            return "ok", hits[0]
        if len(hits) > 1:
            return "ambiguous", hits
    # what was said is part of an option name ("stylo" -> Stylo PG Desk, Stylo Admin)
    part = [o for o in options if len(sq) >= 3 and sq in squash(o)]
    if len(part) == 1:
        return "ok", part[0]
    if len(part) > 1:
        return "ambiguous", part
    # speech-to-text spelling drift ("styllo pgdesk")
    scored = sorted(((difflib.SequenceMatcher(None, sq, squash(o)).ratio(), o) for o in options), reverse=True)
    if scored and scored[0][0] >= 0.78 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.06):
        return "ok", scored[0][1]
    return "none", None


def _list_options(options: list[str], limit: int = 8) -> str:
    shown = options[:limit]
    return ", ".join(shown[:-1]) + (" or " if len(shown) > 1 else "") + shown[-1] + ("…" if len(options) > limit else "")


# ----------------------------------------------------------------------
# Date and time
# ----------------------------------------------------------------------
def _time_in(t: str):
    """-> (hour, minute) or None.  `t` is lower-case, 'p.m.' already folded to 'pm'."""
    if re.search(r"\bnoon\b|\bmidday\b", t):
        return 12, 0
    if re.search(r"\bmidnight\b", t):
        return 0, 0
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b", t)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", t) or re.search(r"\bat (\d{1,2})\b(?!\s*(?:days?|hours?|mins?|minutes?))", t)
        if not m:
            return None
        h, mi, ap = int(m.group(1)), 0, (m.group(2) if m.lastindex and m.lastindex >= 2 else None)
    if mi > 59 or h > 24:
        return None
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    return h % 24, mi


def _date_in(t: str, now: datetime):
    today = now.date()
    if re.search(r"\bday after tomorrow\b", t):
        return today + timedelta(days=2)
    if re.search(r"\byesterday\b", t):
        return today - timedelta(days=1)
    if re.search(r"\btomorrow\b", t):
        return today + timedelta(days=1)
    if re.search(r"\b(?:today|tonight|this evening|this afternoon)\b", t):
        return today
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    mon = "|".join(_MONTHS + [x[:3] for x in _MONTHS])
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?({mon})\b(?:\s+(\d{{4}}))?", t) or None
    d = mo = y = None
    if m:
        d, mo, y = int(m.group(1)), m.group(2), m.group(3)
    else:
        m = re.search(rf"\b({mon})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:\s+(\d{{4}}))?", t)
        if m:
            mo, d, y = m.group(1), int(m.group(2)), m.group(3)
    if m:
        idx = next(i for i, name in enumerate(_MONTHS) if name.startswith(mo[:3]))
        year = int(y) if y else today.year
        try:
            out = date(year, idx + 1, d)
        except ValueError:
            return None
        if not y and out < today:
            out = date(year + 1, idx + 1, d)
        return out
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)   # dd/mm[/yyyy]  (India)
    if m:
        year = int(m.group(3)) if m.group(3) else today.year
        year += 2000 if year < 100 else 0
        try:
            out = date(year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        return out if (m.group(3) or out >= today) else out.replace(year=year + 1)
    m = re.search(rf"\b(?:(next|this|coming|on)\s+)?({'|'.join(_WEEKDAYS)})\b", t)
    if m:
        target = _WEEKDAYS.index(m.group(2))
        delta = (target - today.weekday()) % 7
        if delta == 0 and m.group(1) == "next":
            delta = 7
        return today + timedelta(days=delta)
    return None


def parse_when(text: str, now: datetime):
    """-> dict(dt=datetime|None, date=date|None, time=(h,m)|None). `dt` only when both known."""
    t = norm(text)
    t = re.sub(r"\b([ap])\.?\s?m\.?\b", lambda m: m.group(1) + "m", t)          # p.m. -> pm
    t = _words_to_digits(t)
    rel = re.search(r"\bin (\d+|an?|half an?) (minute|min|hour|day|week)s?\b", t)
    if rel:
        n = 1 if rel.group(1).startswith("a") and not rel.group(1).startswith("half") else (0.5 if rel.group(1).startswith("half") else int(rel.group(1)))
        unit = rel.group(2)
        if unit in ("minute", "min", "hour"):
            dt = (now + (timedelta(hours=n) if unit == "hour" else timedelta(minutes=n))).replace(second=0, microsecond=0)
            return {"dt": dt, "date": dt.date(), "time": (dt.hour, dt.minute)}
        d = now.date() + timedelta(days=int(n) * (7 if unit == "week" else 1))
        tm = _time_in(t)
        return {"dt": datetime(d.year, d.month, d.day, tm[0], tm[1]) if tm else None, "date": d, "time": tm}
    d, tm = _date_in(t, now), _time_in(t)
    dt = datetime(d.year, d.month, d.day, tm[0], tm[1]) if d and tm else None
    return {"dt": dt, "date": d, "time": tm}


def fmt_dt(dt: datetime) -> str:
    return f"{dt:%A} {dt.day} {dt:%B} at {dt.hour % 12 or 12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def parse_now(value) -> datetime:
    try:
        return datetime.fromisoformat(str(value)[:16])
    except ValueError:
        return datetime.now().replace(second=0, microsecond=0)


# ----------------------------------------------------------------------
# Coercion: raw spoken value -> validated form value
# ----------------------------------------------------------------------
def _ok(patch: dict, say: str = "", **extra) -> dict:
    return {"ok": True, "patch": patch, "say": say, **extra}


def _err(msg: str, choices: list[str] | None = None) -> dict:
    return {"ok": False, "error": msg, "choices": choices or []}


def coerce(kind: str, fd: dict, raw, c: C, form: dict) -> dict:
    key, k = fd["key"], fd["kind"]
    flow = c.flow

    if k == "enum":
        options = c.options(fd["options"])
        if not options:
            return _err("There are no options configured for that field.")
        syn = SYNONYMS.get({"environment": "environment", "component": "component", "accessType": "accessType",
                            "accessLevel": "accessLevel", "priority": "priority"}.get(key, ""), None)
        spoken = re.sub(r"\bdev ?ops\b", " ", str(raw), flags=re.I) if key == "environment" else str(raw)
        status, val = match_option(spoken, options, syn, flow.get("choices"))
        if status == "ok":
            patch = {key: val}
            if key == "component" and val == "Frontend":      # same reset the form does by itself
                patch.update({"dbChange": False, "thirdPartyApiChange": False, "thirdPartyApiDetails": "",
                              "envVarChange": False})
            return _ok(patch, val)
        if status == "ambiguous":
            return _err(f"Which one: {_list_options(val)}?", val)
        shown = _list_options(options)
        return _err(f"I don't have {clean(raw)[:40]} for {fd['label'].lower()}. Choose from {shown}.", [])

    if k == "bool":
        b = parse_bool(str(raw))
        if b is None:
            return _err("Please say yes or no.")
        patch = {key: b}
        if key == "thirdPartyApiChange" and not b:
            patch["thirdPartyApiDetails"] = ""
        return _ok(patch, "yes" if b else "no")

    if k == "url":
        t = spoken_symbols(str(raw)).lower()
        m = re.search(r"(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/[^\s]*)?)", t)
        if not m:
            return _err("I couldn't make out a web address. Say it like github dot com slash team slash repo, "
                        "or type it in the form.")
        url = m.group(0)
        url = url if url.startswith("http") else "https://" + url.replace("www.", "", 1)
        return _ok({key: url.rstrip("/.")}, url.rstrip("/."))

    if k == "token":                                   # branch names, versions
        t0 = re.sub(r"^(?:it is|it's|its|the branch is|branch|version|is|called|named)\s+", "", clean(raw), flags=re.I)
        t = re.sub(r"\s+", "-", spoken_symbols(t0).strip())
        if key == "appVersion":
            t = re.sub(r"^[vV]-?(?=\d)", "v", t)
            if re.match(r"^\d", t):
                t = "v" + t
        if not t or len(t) > 120:
            return _err("I didn't catch that. Please say it again, or type it in the form.")
        return _ok({key: t}, t)

    if k == "commit":
        t = re.sub(r"[^0-9a-f]", "", norm(raw).replace(" ", ""))
        if not 6 <= len(t) <= 40:
            return _err("A commit ID is 6 to 40 letters and digits from a to f. Please say it again or type it.")
        return _ok({key: t}, " ".join(t))

    if k == "text":
        t = clean(re.sub(r"^(?:the )?(?:reason|error(?: message)?|impact|details?|notes?|name) (?:is|are|was)\s+", "",
                         clean(raw), flags=re.I))
        t = re.sub(r"^because\s+", "", t, flags=re.I) if key == "reason" else t
        if len(t) < 2:
            return _err("I didn't catch that. Please say it again.")
        return _ok({key: sentence(t)[:500]}, "")

    if k == "service":
        status, val = match_option(str(raw), AWS_SERVICES, {"ELB / ALB": ["alb", "elb", "load balancer"],
                                                             "EC2": ["ec2", "ec 2", "server", "instance"],
                                                             "S3": ["s3", "s 3", "bucket"], "RDS": ["rds", "database"],
                                                             "Route 53": ["route 53", "route53", "dns"]})
        if status == "ok":
            return _ok({key: val}, val)
        t = clean(raw)
        return _ok({key: t[:60]}, t[:60]) if len(t) >= 2 else _err("Which AWS service?")

    if k == "duration":
        t = _words_to_digits(norm(raw))
        n = None
        m = re.search(r"\b(\d{1,3})\s*(day|days|week|weeks|month|months)?\b", t)
        if m:
            n = int(m.group(1))
            unit = m.group(2) or "day"
            n *= 7 if unit.startswith("week") else 30 if unit.startswith("month") else 1
        elif re.search(r"\ba week\b|\bone week\b", t):
            n = 7
        elif re.search(r"\ba month\b", t):
            n = 30
        elif re.search(r"\ba day\b|\btomorrow\b", t):
            n = 1
        if not n or n < 1 or n > 365:
            return _err("Please tell me a number of days, like 7 or 30.")
        if n in DURATIONS:
            return _ok({key: n}, f"{n} day{'s' if n != 1 else ''}")
        return _ok({key: "Custom", "customDays": str(n)}, f"{n} days")

    if k == "int":
        t = _words_to_digits(norm(raw))
        m = re.search(r"\b(\d{1,3})\b", t)
        if not m or int(m.group(1)) < 1:
            return _err("Please say a number of days.")
        return _ok({key: m.group(1)}, f"{m.group(1)} days")

    if k == "datetime":
        return _coerce_datetime(kind, fd, raw, c)

    if k == "envvars":
        return _coerce_envvars(raw, form)

    return _err("I can't fill that field by voice.")


def _coerce_datetime(kind: str, fd: dict, raw, c: C) -> dict:
    p = parse_when(str(raw), c.now)
    d, tm, dt = p["date"], p["time"], p["dt"]
    pending = None
    try:
        pending = date.fromisoformat(c.flow["pending_date"]) if c.flow.get("pending_date") else None
    except ValueError:
        pending = None
    if dt is None and tm and not d and pending:
        dt = datetime(pending.year, pending.month, pending.day, tm[0], tm[1])
    elif dt is None and tm and not d:                                  # only a time: next time it happens
        dt = datetime(c.now.year, c.now.month, c.now.day, tm[0], tm[1])
        if dt < c.now:
            dt += timedelta(days=1)
    if dt is None and d and not tm:
        return {"ok": False, "error": f"What time on {d.day} {d:%B}?", "choices": [],
                "flow_patch": {"pending_date": d.isoformat()}}
    if dt is None:
        return _err("I didn't catch the date and time. Say something like tomorrow at 10 PM, or 12 November at 9:30 AM.")
    if kind == "DEPLOYMENT" and dt < c.now.replace(second=0, microsecond=0):
        return {"ok": False, "error": "That time has already passed. Please give a future date and time.",
                "choices": [], "flow_patch": {"pending_date": None}}
    return _ok({fd["key"]: dt.strftime("%Y-%m-%dT%H:%M")}, fmt_dt(dt), flow_patch={"pending_date": None})


def _coerce_envvars(raw, form: dict) -> dict:
    t = clean(raw)
    if re.match(r"^(?:i will|i'll|let me|i am going to)\b.*\b(?:type|upload|add|enter)\b|^(?:upload|manual)", norm(t)):
        return {"ok": True, "patch": {}, "say": "", "skip": True}
    if re.match(r"^(?:done|that'?s all|that is all|finished|no more|nothing else)\b", norm(t)):
        rows = form.get("envVars") or []
        if any(r.get("key") and r.get("hasValue") for r in rows):
            return {"ok": True, "patch": {}, "say": "", "finish": True}
        return _err("I don't have any complete variable yet. Say NAME equals value, or say I will type them.")
    rows = []
    for part in re.split(r"\s*(?:;|,\s*and\s+|\band\b\s+(?=[A-Za-z_][\w ]*\s+(?:equals|=|is)\s))\s*", t):
        m = re.match(r"^\s*(?:variable\s+|key\s+|name\s+)?([A-Za-z_][\w ]{0,60}?)\s*(?:=|equals|is|value)\s+(.+?)\s*$", part, re.I)
        if m:
            key = re.sub(r"\s+", "_", m.group(1).strip()).upper()
            rows.append({"key": key, "value": spoken_symbols(m.group(2)) if re.search(r"\b(?:dot|slash|colon)\b", m.group(2)) else m.group(2).strip()})
    if not rows:
        return _err("Say each variable like API URL equals https colon slash slash example dot com. "
                    "Or say I will type them.")
    return {"ok": True, "patch": {"envVarsAdd": rows}, "say": "added"}


# ----------------------------------------------------------------------
# Field bookkeeping
# ----------------------------------------------------------------------
def _fields(kind: str) -> list[dict]:
    return FORMS[kind]["fields"]


def _all_fields(kind: str) -> list[dict]:
    return _fields(kind) + FORMS[kind]["optional"]


def _field(kind: str, key: str) -> dict | None:
    return next((f for f in _all_fields(kind) if f["key"] == key), None)


def active_fields(kind: str, form: dict) -> list[dict]:
    return [f for f in _fields(kind) if not f.get("when") or f["when"](form)]


def _blank(v) -> bool:
    return v is None or v == "" or v == []


def satisfied(fd: dict, form: dict, flow: dict) -> bool:
    key = fd["key"]
    if key in flow.get("skipped", []):
        return True
    if fd["kind"] == "envvars":      # rows are not enough: the user says "done" when the list is complete
        return key in flow.get("confirmed", []) and any(r.get("key") and r.get("hasValue") for r in (form.get("envVars") or []))
    v = form.get(key)
    if fd["kind"] == "bool":
        return v is True or key in flow.get("confirmed", [])
    if "default" in fd:
        return (not _blank(v)) and (key in flow.get("confirmed", []) or str(v) != str(fd["default"]))
    return not _blank(v)


def next_missing(kind: str, form: dict, flow: dict) -> dict | None:
    return next((f for f in active_fields(kind, form) if f["required"] and not satisfied(f, form, flow)), None)


def display(fd: dict, form: dict) -> str:
    v = form.get(fd["key"])
    if fd["kind"] == "envvars":
        n = len([r for r in (v or []) if r.get("key")])
        return f"{n} variable{'s' if n != 1 else ''}" if n else ""
    if fd["kind"] == "bool":
        return "Yes" if v else "No"
    if fd["kind"] == "datetime" and v:
        try:
            return fmt_dt(datetime.fromisoformat(v))
        except ValueError:
            return str(v)
    if fd["key"] == "durationDays":
        return f"{form.get('customDays')} days" if v == "Custom" else f"{v} day{'s' if v != 1 else ''}"
    s = "" if v is None else str(v)
    return s if len(s) <= 60 else s[:57] + "…"


def build_progress(kind: str, form: dict, flow: dict, asking: str | None) -> dict:
    items, filled = [], 0
    for fd in active_fields(kind, form):
        if fd["required"]:
            ok = satisfied(fd, form, flow)
            filled += ok
            items.append({"key": fd["key"], "label": fd["label"], "required": True,
                          "status": "filled" if ok else ("asking" if fd["key"] == asking else "todo"),
                          "display": display(fd, form) if ok else ""})
    for fd in FORMS[kind]["optional"]:
        if not _blank(form.get(fd["key"])):
            items.append({"key": fd["key"], "label": fd["label"], "required": False, "status": "filled",
                          "display": display(fd, form)})
    manual = []
    if kind == "DEPLOYMENT" and form.get("dbChange") is True and not form.get("dbChangeFileName"):
        manual.append("Attach the DB / schema change file with the upload button.")
    if "envVars" in flow.get("skipped", []) and not any(r.get("key") for r in (form.get("envVars") or [])):
        manual.append("Add the environment variables or upload your .env file.")
    return {"title": FORMS[kind]["title"], "fields": items, "filled": filled,
            "total": sum(1 for i in items if i["required"]), "manual": manual}


# ----------------------------------------------------------------------
# Understanding: rule-based extraction
# ----------------------------------------------------------------------
_CANCEL = re.compile(r"^(?:cancel|discard|abort|forget it|never ?mind|close (?:the |this )?(?:form|request)|stop|start over)\b")
_SUBMIT = re.compile(r"^(?:please )?(?:submit|send|confirm|finish|file|place|raise|create it|go ahead and (?:submit|send)|do it)\b"
                     r"(?: it| this| the request| the form| now)*$|^(?:submit|send) (?:it|this|the) ")
_STATUS = re.compile(r"\b(?:what(?:'s| is) (?:left|missing|remaining|pending)|what else|how many (?:left|more)|status|"
                     r"read (?:it )?back|summary|summari[sz]e|where are we)\b")
_BACK = re.compile(r"^(?:please )?(?:go back|back|step back|previous(?: question| one| step)?|undo(?: that| it| last)?|"
                   r"(?:go )?one step back|go back (?:one|a) step|change (?:the )?(?:last|previous) (?:one|answer))$")
_REVIEW = re.compile(r"^(?:please )?(?:review|(?:let me )?review (?:it|the form|everything)|read (?:it |the form |everything )?(?:out|back|aloud)|"
                     r"check (?:it|the form|everything)|what (?:have i|did i) (?:filled|fill|said))(?: please)?$")
_REPEAT = re.compile(r"^(?:repeat|say (?:that )?again|what was (?:the|that) question|pardon|sorry)\b")
_KEEP = re.compile(r"^(?:keep(?: it)?|leave it|same|default|as is|fine|that'?s fine|no change|it'?s fine|ok(?:ay)? as is)\b")
_SKIP = re.compile(r"^(?:skip(?: it| this| that)?|pass|not now|later|next|none|no|nothing)$")


def _free_text(fd: dict | None) -> bool:
    return bool(fd) and fd["kind"] in ("text", "envvars")


def rules_extract(kind: str, text: str, form: dict, flow: dict, c: C) -> dict:
    """-> {key: raw}. Only keys that are in the form for this kind."""
    t = norm(text)
    asking = flow.get("asking")
    out: dict[str, str] = {}
    keys = {f["key"] for f in _all_fields(kind)}

    # "change the branch to main", "set environment to QA"
    m = re.match(r"^(?:please )?(?:change|set|update|make|use|put|edit|correct)\s+(?:the\s+|my\s+)?(.+?)\s+(?:to|as|=|with)\s+(.+)$", clean(text), re.I)
    if m:
        label = norm(m.group(1))
        for key, words in FIELD_WORDS.items():       # dict order puts "rollback branch" before "branch"
            if key in keys and re.fullmatch(words, label):
                out[key] = m.group(2)
                return out
    if asking and asking != OPTIONAL_KEY and asking in keys:
        out[asking] = text
        fd = _field(kind, asking)
        if _free_text(fd):
            return out
    if asking == OPTIONAL_KEY:
        for key, pat in (("rollbackBranch", r"\broll ?back(?: branch)?\s+(?:is\s+|to\s+)?([\w./\-]+)"),
                         ("appVersion", r"\bversion\s+(?:is\s+)?(\S+)"), ("githubCommit", r"\bcommit(?: id)?\s+(?:is\s+)?([0-9a-f ]{6,45})")):
            mm = re.search(pat, t)
            if mm and key in keys:
                out[key] = mm.group(1)
        for key, pat in (("applicationChangeDetails", r"\b(?:change details?|changes?)\s*(?:are|is|:)?\s+(.+?)(?=\s+(?:notes?|additional info\w*)\b|$)"),
                         ("additionalInfo", r"\b(?:notes?|additional info\w*|comments?)\s*(?:are|is|:)?\s+(.+)$")):
            mm = re.search(pat, clean(text), re.I)
            if mm and key in keys:
                out[key] = mm.group(1)
        if not out and len(t) > 3:
            out["additionalInfo"] = text
        return out

    if "name" in keys:
        mm = re.search(r"\b(?:called|named|name(?: is)?)\s+(.+)$", clean(text), re.I)
        if mm:
            out["name"] = mm.group(1)

    # explicit mentions anywhere in the sentence (also makes "create a deployment for stylo on prod" work)
    def put(key, raw):
        if key in keys and key not in out and raw:
            out[key] = raw
    if "project" in keys and c.apps:
        status, val = match_option(t, c.apps)
        if status == "ok" and squash(val) in squash(t):
            put("project", val)
    if "environment" in keys:
        mm = re.search(r"\b(prod(?:uction)?|dev(?:elopment)?|qa|uat|staging)\b", re.sub(r"\bdev ?ops\b", " ", t))
        put("environment", mm.group(1) if mm else None)
    if "component" in keys:
        mm = re.search(r"\b(front ?end|back ?end)\b", t)
        put("component", mm.group(1) if mm else None)
    if "dateTime" in keys:
        p = parse_when(text, c.now)
        if p["date"] or p["time"]:
            put("dateTime", text)
    mm = re.search(r"((?:https?://)?(?:www\.)?github\.com/[^\s]+)", spoken_symbols(text), re.I)
    if mm:
        put("githubUrl", mm.group(1))
    for key, pat in (("rollbackBranch", r"\broll ?back(?: branch)?\s+(?:is\s+|to\s+)?([\w./\- ]+?)(?=\s+(?:and|with|branch|version|commit)\b|$)"),
                     ("githubBranch", r"(?<!roll)(?<!rollback )\bbranch\s+(?:is\s+|name\s+)?([\w./\-]+)"),
                     ("appVersion", r"\bversion\s+(?:is\s+)?(v?\d[\w.\-]*)"),
                     ("githubCommit", r"\bcommit(?: id)?\s+(?:is\s+)?([0-9a-f]{6,40})\b")):
        mm = re.search(pat, t)
        if mm:
            put(key, mm.group(1))
    if "accessType" in keys:
        st, val = match_option(t, ACCESS_TYPES, SYNONYMS["accessType"])
        if st == "ok" and re.search(r"\baccess\b|\b(?:to|for)\b", t):
            put("accessType", t)
    if "accessLevel" in keys:
        mm = re.search(r"\b(read only|read ?write|read and write|full access|admin(?:istrator)?)\b", t)
        put("accessLevel", mm.group(1) if mm else None)
    if "durationDays" in keys:
        mm = re.search(r"\bfor (\d+|a|one|two|three|four|five|six|seven|ten|fifteen|thirty) (day|days|week|weeks|month|months)\b", t)
        put("durationDays", mm.group(0) if mm else None)
    if "priority" in keys:
        mm = re.search(r"\b(critical|urgent|high|medium|low)(?: priority)?\b", t)
        put("priority", mm.group(1) if mm else None)
    if "service" in keys:
        st, val = match_option(t, AWS_SERVICES)
        put("service", val if st == "ok" and len(squash(val)) >= 3 and val != "Other" else None)
    return out


# ----------------------------------------------------------------------
# Understanding: Claude (optional)
# ----------------------------------------------------------------------
def _api_key() -> str:
    try:
        from .config import settings
        return getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    except Exception:  # config needs pydantic; tests run without it
        return ""


def _model() -> str:
    try:
        from .config import settings
        return getattr(settings, "VOICE_LLM_MODEL", "claude-haiku-5-5")
    except Exception:
        return "claude-haiku-5-5"


def _redacted(kind: str, form: dict) -> dict:
    """What the model may see: no uploaded files, no env-var names/values."""
    out = {}
    for fd in _all_fields(kind):
        if fd["kind"] == "envvars":
            continue
        if not _blank(form.get(fd["key"])):
            out[fd["key"]] = form[fd["key"]]
    return out


def _tool_schema(kind: str, c: C) -> dict:
    props: dict = {}
    for fd in _all_fields(kind):
        k = fd["kind"]
        if k == "envvars":
            continue
        if k == "enum":
            props[fd["key"]] = {"type": "string", "enum": c.options(fd["options"])}
        elif k == "bool":
            props[fd["key"]] = {"type": "boolean"}
        elif k == "datetime":
            props["date"] = {"type": "string", "description": "YYYY-MM-DD, only if the user gave a date"}
            props["time"] = {"type": "string", "description": "HH:MM 24-hour, only if the user gave a time"}
        elif k == "duration":
            props[fd["key"]] = {"type": "integer", "description": "number of days"}
        elif k == "url":
            props[fd["key"]] = {"type": "string", "description": "full https URL"}
        elif k == "service":
            props[fd["key"]] = {"type": "string", "description": "AWS service, e.g. EC2, S3, RDS, Lambda"}
        else:
            props[fd["key"]] = {"type": "string"}
    props["command"] = {"type": "string", "enum": ["none", "cancel", "skip", "show_status", "repeat"],
                        "description": "none for normal answers"}
    return {"name": "update_form", "description": "Record the values the user just spoke for the form.",
            "input_schema": {"type": "object", "properties": props}}


def llm_extract(kind: str, text: str, form: dict, flow: dict, c: C, user_name: str) -> dict | None:
    key = _api_key()
    if not key:
        return None
    asking = flow.get("asking")
    fd = _field(kind, asking) if asking and asking != OPTIONAL_KEY else None
    system = (
        f"You help {user_name} fill in a '{FORMS[kind]['title']}' form in OPSFlow by voice. Speech-to-text may contain "
        "small mistakes. Call update_form exactly once with ONLY what the user clearly said in this message (or "
        "corrected). Never invent values, URLs, branch names or commit IDs. Enum fields must use one of the allowed "
        "values. Keep free-text fields in the user's own words, tidied up. "
        f"Now: {c.now:%A %Y-%m-%d %H:%M} (local). Resolve relative dates like 'tomorrow' or 'next Friday' from that. "
        + (f"The question just asked was about '{fd['label']}' ({asking}); a bare answer belongs to that field. " if fd else "")
        + (f"The user was just asked whether to add optional details (version, commit, change details, notes). " if asking == OPTIONAL_KEY else "")
        + f"Current form values: {json.dumps(_redacted(kind, form))}. Applications: {', '.join(c.apps)}."
    )
    body = {"model": _model(), "max_tokens": 250, "system": system, "tools": [_tool_schema(kind, c)],
            "tool_choice": {"type": "tool", "name": "update_form"}, "messages": [{"role": "user", "content": text}]}
    try:
        from . import llm   # keep-alive connection: no new TLS handshake on every sentence
        found = llm.first_tool_use(llm.call(body, timeout=4.0))
        if found:
            return found[1]
    except Exception:  # never let the AI layer break the assistant
        log.exception("Voice form LLM call failed; using the rule-based parser.")
    return None


# ----------------------------------------------------------------------
# The turn
# ----------------------------------------------------------------------
def can_use(kind: str, role: str, is_admin: bool) -> str | None:
    """-> error text, or None when allowed."""
    spec = FORMS.get(kind)
    if not spec:
        return "I can't fill that form by voice."
    if spec.get("admin_only") and not is_admin:
        return spec["role_msg"]
    if spec.get("roles") and role not in spec["roles"]:
        return spec["role_msg"]
    return None


def _question(fd: dict, c: C, form: dict | None = None) -> str:
    q = fd["ask"]
    if fd["kind"] == "envvars" and any(r.get("key") for r in ((form or {}).get("envVars") or [])):
        return "Any more variables? Say NAME equals value, or say done."
    if "{options}" in q:
        q = q.replace("{options}", _list_options(c.options(fd["options"])))
    if "default" in fd and fd["kind"] != "bool":
        shown = display(fd, {fd["key"]: fd["default"]})
        q += f" Say keep to stay with {shown}."
    return q


def _ack(applied: list[tuple[dict, str]]) -> str:
    if not applied:
        return ""
    if len(applied) > 3:
        return f"Got it, I filled in {len(applied)} fields. "
    bits = []
    for fd, say in applied:
        if fd["kind"] == "bool":
            bits.append(("" if say == "yes" else "no ") + fd["label"].lower())
        elif say:
            bits.append(say if fd["kind"] in ("enum", "service") and fd["key"] in ("project",) else f"{fd['label'].lower()} {say}")
        else:
            bits.append(f"{fd['label'].lower()} noted")
    return "Got it, " + ", ".join(bits) + ". "


def turn(kind: str, text: str, form: dict, flow: dict, now, apps, envs, priorities, user_name: str = "",
         start: bool = False, role: str = "") -> dict:
    """One conversational turn. Pure function of its inputs (no I/O except the optional Claude call)."""
    flow = dict(flow or {})
    flow.setdefault("confirmed", [])
    flow.setdefault("skipped", [])
    form = dict(form or {})
    c = C(apps, envs, priorities, parse_now(now), flow, role)
    spec = FORMS[kind]
    t = norm(text)
    short = len(t.split()) <= 6                       # commands are short; dictated prose is not
    asking = flow.get("asking")
    intro = f"Okay, let's create a {spec['title']}. " if start else ""
    patch: dict = {}
    applied: list[tuple[dict, str]] = []
    errors: list[str] = []
    handled = False

    def respond(speech: str, intent: str = "form", **extra) -> dict:
        flow["asking"] = extra.pop("asking", flow.get("asking"))
        merged = {**form, **patch}
        return {"intent": intent, "speech": speech, "patch": patch, "flow": flow, "kind": kind,
                "progress": build_progress(kind, merged, flow, flow.get("asking")), **extra}

    def ask_next(prefix: str = "") -> dict:
        merged = {**form, **patch}
        fd = next_missing(kind, merged, flow)
        if fd:
            q = _question(fd, c, merged)
            flow["asking"], flow["last_question"] = fd["key"], q
            return respond(prefix + q)
        if spec["optional"] and not flow.get("optional_asked"):
            flow["optional_asked"], flow["asking"], flow["last_question"] = True, OPTIONAL_KEY, spec["optional_ask"]
            return respond(prefix + "That covers the required details. " + spec["optional_ask"])
        flow["asking"], flow["last_question"] = None, ""
        notes = build_progress(kind, merged, flow, None)["manual"]
        msg = prefix + f"All set. Please review the {spec['title']} on screen and click Submit yourself when you're ready."
        if notes:
            msg += " " + " ".join(notes)
        return respond(msg, done=True)

    # ---- commands that never touch the form ----
    if not start and short:
        if _BACK.match(t):
            # ONE STEP BACK: clear the last answer given by voice and ask that question again.
            order = list(flow.get("order") or [])
            while order and not _field(kind, order[-1]):
                order.pop()
            if not order:
                return respond(f"Okay, I closed the {spec['title']}.", "form_cancel")
            key = order.pop()
            flow["order"] = order
            fd = _field(kind, key)
            blank = fd["default"] if "default" in fd else (False if fd["kind"] == "bool" else "")
            patch[key] = blank
            if key == "durationDays":
                patch["customDays"] = ""
            flow["confirmed"] = [k for k in flow["confirmed"] if k != key]
            flow["skipped"] = [k for k in flow["skipped"] if k != key]
            flow["optional_asked"] = False if key in {f["key"] for f in spec["optional"]} else flow.get("optional_asked")
            q = _question(fd, c, {**form, **patch})
            flow["asking"], flow["last_question"] = key, q
            return respond(f"Okay, one step back. {q}", asking=key)
        if _REVIEW.match(t):
            prog = build_progress(kind, form, flow, asking)
            got = [f"{i['label']}: {i['display']}" for i in prog["fields"] if i["status"] == "filled" and i["display"]]
            left = [i["label"].lower() for i in prog["fields"] if i["required"] and i["status"] != "filled"]
            msg = ("Here is what I have. " + ". ".join(got) + ". ") if got else "Nothing is filled yet. "
            msg += (f"Still needed: {', '.join(left)}." if left else "Everything required is filled. Click Submit yourself when you're ready, "
                    "then say go back or open any page.")
            return respond(msg, review=True, asking=asking)
        if _CANCEL.match(t):
            return respond(f"Okay, I cancelled the {spec['title']}.", "form_cancel")
        if _SUBMIT.search(t):
            fd = next_missing(kind, form, flow)
            more = f" I still need the {fd['label'].lower()} first." if fd else ""
            return respond("I can't submit it for you. Please review the form and click Submit yourself." + more)
        if _STATUS.search(t) and asking != OPTIONAL_KEY:
            prog = build_progress(kind, form, flow, asking)
            left = [i["label"].lower() for i in prog["fields"] if i["required"] and i["status"] != "filled"]
            msg = (f"{prog['filled']} of {prog['total']} required details are filled. "
                   + (f"Still needed: {', '.join(left)}." if left else "Everything required is filled. Please review and click Submit."))
            fd = next_missing(kind, form, flow)
            return respond(msg + (" " + _question(fd, c) if fd else ""), asking=fd["key"] if fd else asking)
        if _REPEAT.match(t) and flow.get("last_question"):
            return respond(flow["last_question"])

    # ---- the optional "anything else?" question ----
    if asking == OPTIONAL_KEY and short and (
            parse_bool(t) is False or _SKIP.match(t) or re.match(r"^(?:nothing|that'?s all|that is all|no thanks|done)\b", t)):
        flow["asking"] = None
        return ask_next("Okay. ")

    # ---- keep / skip / "I will type it" for the field being asked ----
    fd_asked = _field(kind, asking) if asking and asking != OPTIONAL_KEY else None
    if fd_asked and short:
        key = fd_asked["key"]
        if _KEEP.match(t) and (fd_asked["kind"] == "bool" or ("default" in fd_asked and not _blank(form.get(key)))):
            flow["confirmed"] = sorted(set(flow["confirmed"]) | {key})
            return ask_next("Okay. ")
        if fd_asked["kind"] == "envvars" and re.match(r"^(?:i will|i'll|let me|upload|manual)", t):
            flow["skipped"] = sorted(set(flow["skipped"]) | {"envVars"})
            return ask_next("Okay, you can add them in the form. ")
        if fd_asked["kind"] not in ("bool", "envvars") and _SKIP.match(t):
            if fd_asked["required"]:
                return respond("That one is required, so I can't skip it. " + (flow.get("last_question") or ""), asking=asking)
            return ask_next("Okay. ")

    # ---- understand ----
    raw: dict = {}
    command = "none"
    use_llm = not (fd_asked and fd_asked["kind"] == "envvars")     # never send secrets to the model
    if use_llm and fd_asked and len(t.split()) <= 6:
        # SPEED: a short, direct answer to the question just asked is understood by the rules in
        # microseconds; only call the AI (~1 s) when the rules cannot validate it.
        try:
            r0 = rules_extract(kind, text, form, flow, c)
            if set(r0) == {fd_asked["key"]} and coerce(kind, fd_asked, r0[fd_asked["key"]], c, {**form, **patch}).get("ok"):
                use_llm = False
        except Exception:
            pass
    llm = llm_extract(kind, text, form, flow, c, user_name or "the user") if use_llm else None
    if llm is not None:
        command = llm.get("command", "none")
        for k, v in llm.items():
            if k in ("command", "date", "time") or v in (None, "", []):
                continue
            raw[k] = v
        if llm.get("date") or llm.get("time"):
            raw["dateTime"] = f"{llm.get('date', '')} {llm.get('time', '')}".strip()
        if fd_asked and not raw and command == "none":
            raw[fd_asked["key"]] = text                            # a bare answer the model left out
    else:
        raw = rules_extract(kind, text, form, flow, c)
    if command == "cancel":
        return respond(f"Okay, I cancelled the {spec['title']}.", "form_cancel")
    if command == "repeat" and flow.get("last_question"):
        return respond(flow["last_question"])

    # ---- validate and apply ----
    for key, value in raw.items():
        fd = _field(kind, key)
        if not fd:
            continue
        if key == "dateTime" and llm is not None:
            value = _iso_to_phrase(str(value).strip())
        res = coerce(kind, fd, value, c, {**form, **patch})
        for fk, fv in (res.get("flow_patch") or {}).items():
            flow[fk] = fv
        if res.get("ok"):
            if res.get("skip"):
                flow["skipped"] = sorted(set(flow["skipped"]) | {key})
                continue
            patch.update(res["patch"])
            if res.get("finish"):
                flow["confirmed"] = sorted(set(flow["confirmed"]) | {key})
                handled = True
                continue
            applied.append((fd, res.get("say", "")))
            flow["order"] = [k for k in (flow.get("order") or []) if k != key] + [key]
            if fd["kind"] in ("enum", "bool", "duration") or "default" in fd:
                flow["confirmed"] = sorted(set(flow["confirmed"]) | {key})
            flow["choices"] = []
        else:
            errors.append(res["error"])
            if res.get("choices"):
                flow["choices"] = res["choices"]
                flow["asking"] = key

    if start:                                                   # the opening sentence may carry values
        return ask_next(intro + _ack(applied))
    if errors and not applied:
        fd = fd_asked or next_missing(kind, {**form, **patch}, flow)
        retry = errors[0] if errors[0].endswith("?") else "Sorry. " + errors[0]
        if flow.get("asking") == OPTIONAL_KEY:
            retry += " " + spec["optional_ask"]
        return respond(retry, asking=flow.get("asking") or (fd["key"] if fd else None))
    if handled and not applied and not errors:
        flow["asking"] = None
        return ask_next("Okay. ")
    if not applied and not errors:
        if asking:
            return respond("Sorry, I didn't catch that. " + (flow.get("last_question") or ""), asking=asking)
        return respond("Tell me what to change, or review the form and click Submit when you're ready.", done=True)

    prefix = _ack(applied) + (errors[0] + " " if errors else "")
    if asking == OPTIONAL_KEY or (asking and asking in {f["key"] for f, _ in applied}):
        flow["asking"] = None
    return ask_next(prefix)


def _iso_to_phrase(s: str) -> str:
    """'2026-11-06 22:00' (from the model) -> a phrase parse_when understands."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?: (\d{2}):(\d{2}))?$", s)
    if m:
        return f"{m.group(1)} at {m.group(2)}:{m.group(3)}" if m.group(2) else m.group(1)
    m = re.match(r"^(\d{2}):(\d{2})$", s)
    return f"at {m.group(1)}:{m.group(2)}" if m else s


# ----------------------------------------------------------------------
# Entry point (called from main.py)
# ----------------------------------------------------------------------
def handle_voice_form(db, body: dict, ctx):
    from . import logic
    from .auth_helpers import is_admin, require_auth

    user = require_auth(ctx)
    kind = str(body.get("kind") or "").upper()
    err = can_use(kind, user.role, is_admin(user))
    if err:
        return {"intent": "error", "speech": err}
    cfg = logic.handle_get_config(db)
    out = turn(
        kind, str(body.get("text") or "")[:600], body.get("form") or {}, body.get("flow") or {}, body.get("now"),
        cfg.get("applications", []), cfg.get("environments", []), cfg.get("priorities") or DEFAULT_PRIORITIES,
        user_name=(user.name or "").split(" ")[0], start=bool(body.get("start")), role=user.role,
    )
    return out
