"""
Voice assistant brain for OPSFlow  (action: voiceCommand).

The browser turns speech into text; this module turns the text into an
answer + an action for the UI:

    "open deployment 123"               -> opens DEP-000123
    "show failed deployments for prod"  -> filtered list (+ page link)
    "how many pending access requests"  -> spoken count
    "who requested deployment 123?"     -> spoken answer from the real record
    "approve it" / "mark this as failed"-> uses the record on screen / the last one talked about
    "assign deployment 123 to Eswar"    -> asks the UI to confirm, then reassigns (admin)
    "set the rollback branch of 123 to release/1.0" -> confirm, then edits (DevOps)
    "create a new deployment"           -> opens the form and fills it turn by turn (voice_form.py)
    anything else                       -> the AI agent (below)

How the text is understood  (fast first, smart when needed)
  1. A rule-based parser answers common commands in a few milliseconds.
     It knows the CONTEXT the browser sends: the record on screen, the last
     results, the last record talked about ("open it", "approve this one").
  2. If the rules do not understand, the sentence is long / conversational,
     or something is ambiguous, and ANTHROPIC_API_KEY is set, a Claude AGENT
     takes over. It remembers the last few turns of the conversation, can LOOK
     THINGS UP (get_record / find_records / search_records, read-only) and then
     picks exactly one action, or speaks an answer built only from real data.
     Claude only chooses; this module executes, so it can never do more than a
     button in the UI could, and every permission rule still applies.
  3. Without a key, the rules + a normal OPSFlow search are used.

Nothing here changes data. Status changes, edits and reassignments are returned
as an `action` that the UI confirms out loud ("Shall I approve deployment 123?")
and only then sends through the normal API calls, so every permission rule,
status rule, audit entry and e-mail still applies.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import logic, llm
from .auth_helpers import Ctx, require_auth, is_admin
from .config import settings
from .errors import ApiError
from .models import User

log = logging.getLogger("opsflow.voice")

KINDS = ("DEPLOYMENT", "ACCESS", "AWS_ISSUE")
KIND_LABEL = {"DEPLOYMENT": "deployment", "ACCESS": "access request", "AWS_ISSUE": "AWS issue"}
KIND_PLURAL = {"DEPLOYMENT": "deployments", "ACCESS": "access requests", "AWS_ISSUE": "AWS issues"}
KIND_ROUTE = {"DEPLOYMENT": "/deployments", "ACCESS": "/access", "AWS_ISSUE": "/aws-issues"}
KIND_PREFIX = {"DEPLOYMENT": "DEP", "ACCESS": "ACC", "AWS_ISSUE": "AWS"}

STATUS_SPOKEN = {
    "REQUESTED": "pending", "APPROVED": "approved", "REJECTED": "rejected", "IN_PROGRESS": "in progress",
    "COMPLETED_SUCCESS": "successful", "COMPLETED_FAILED": "failed", "ROLLED_BACK": "rolled back",
    "ACCESS_GIVEN": "access-given", "OPEN": "open", "RESOLVED": "resolved",
}
NEEDS_REASON = {"REJECTED", "COMPLETED_FAILED", "ROLLED_BACK"}
ENVIRONMENTS = {"DEV": r"(?:dev|development)", "QA": r"qa", "UAT": r"uat", "PROD": r"(?:prod|production)"}

EXAMPLES = [
    "Open deployment 123",
    "Show failed deployments",
    "How many pending access requests?",
    "Show prod deployments today",
    "Approve deployment 123",
    "Who requested deployment 123?",
    "Create a new deployment",
    "Search stylo",
]

# ---------------------------------------------------------------------
# Text clean-up
# ---------------------------------------------------------------------

_DIGIT_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_RECORD_WORDS = {"deployment", "deployments", "dep", "access", "acc", "issue", "aws", "number", "no", "id", "request"}

_WAKE_RE = re.compile(
    r"^(?:hello|helo|hullo|hallo|hey|hay|ok|okay)\s+(?:ops ?flow|ops|opps|obs|oops|apps|hops)\b\s*"
)
_FILLER_RE = re.compile(
    r"^(?:(?:please|can you|could you|would you|will you|i want to|i wanna|i need to|i would like to|i'd like to|let's|lets)\s+)+"
)


def _numberize(t: str) -> str:
    """'five six seven 8' -> '5678'; a lone digit word is only converted after
    a record word ('deployment five' -> 'deployment 5')."""
    out, run, prev = [], [], ""

    def flush():
        nonlocal run
        if run:
            digits = "".join(_DIGIT_WORDS.get(w, w) for w in run)
            if len(run) > 1 or run[0].isdigit() or prev in _RECORD_WORDS:
                out.append(digits)
            else:
                out.extend(run)
            run = []

    for tok in t.split():
        if tok.isdigit() or tok in _DIGIT_WORDS:
            run.append(tok)
            continue
        flush()
        out.append(tok)
        prev = tok
    prev = out[-1] if out else ""
    flush()
    return " ".join(out)


def normalize(text: str) -> str:
    t = str(text or "").lower().replace("&", " and ")
    t = re.sub(r"[^\w\s'\-]", " ", t)
    t = re.sub(r"(?<=\d)[\s\-]+(?=\d)", "", t)          # '5678 9778' / '5678-9778' -> '56789778'
    t = re.sub(r"\s+", " ", t).strip()
    t = _WAKE_RE.sub("", t)
    t = _FILLER_RE.sub("", t)
    t = re.sub(r"\s+(?:please|thanks|thank you)$", "", t)
    return _numberize(t).strip()


# ---------------------------------------------------------------------
# Parser: text -> plan
# ---------------------------------------------------------------------

_DISMISS = re.compile(r"^(?:thanks?(?: you)?|thank you|bye|goodbye|good bye|that'?s all|that is all|never ?mind|"
                      r"cancel|stop|close|dismiss|nothing|no thanks|no thank you|go to sleep|sleep)\b")
_GREET = re.compile(r"^(?:hi|hello|hey|good (?:morning|afternoon|evening))$")
_HELP = re.compile(r"^(?:help|what can you do|what do you do|how can you help|what can i say|show commands|commands|how do i use)\b")
_WHOAMI = re.compile(r"\bwho am i\b|\bmy role\b|\bwhat'?s my name\b")
_LOGOUT = re.compile(r"\b(?:log ?out|sign ?out)\b")
_BACK = re.compile(r"^(?:go )?back$|^go back\b|^previous page$")
_SUMMARY = re.compile(r"\b(?:summary|overview|status report|how (?:is|are) (?:everything|things)|"
                      r"what'?s (?:going on|happening|new)|any updates?|catch me up)\b")
_COUNT = re.compile(r"\bhow many\b|\bcount\b|\bnumber of\b|\btotal\b")
_CREATE = re.compile(r"^(?:create|raise|add|make|submit|file|log|report|request|new|(?:open|start)\s+(?:a\s+)?new)\b")
_SEARCH = re.compile(r"^(?:search|find|look(?:ing)? (?:up|for)|lookup|where is|anything about)\s+(?:for\s+)?(.+)$")
_LISTY = re.compile(r"^(?:show|list|display|how|what|which|find|search|count|any|are|is|tell|who|when|where)\b")

_STOPWORDS = set("""a an the me my to of for on in at is are was were be been do does did can could would will
show list display get give tell find search look looking up please all any some there this that and or
open go take view see check about with from""".split())


def _kind(t: str) -> str | None:
    if re.search(r"\b(?:aws|issues?|incidents?|outages?)\b", t):
        return "AWS_ISSUE"
    if re.search(r"\b(?:access(?:es)?|acc|permissions?)\b", t):
        return "ACCESS"
    if re.search(r"\b(?:deployments?|deploys?|dep|releases?)\b", t):
        return "DEPLOYMENT"
    return None


def _env(t: str) -> str | None:
    t = re.sub(r"\bdev ?ops\b", " ", t)
    for env, pattern in ENVIRONMENTS.items():
        if re.search(rf"\b{pattern}\b", t):
            return env
    return None


def _project(t: str, apps: list[str]) -> str | None:
    squashed = re.sub(r"[^a-z0-9]", "", t)
    best = None
    for a in apps:
        key = re.sub(r"[^a-z0-9]", "", a.lower())
        if len(key) >= 3 and key in squashed and (best is None or len(key) > len(re.sub(r"[^a-z0-9]", "", best.lower()))):
            best = a
    return best


def _date(t: str) -> str | None:
    for word in ("today", "tomorrow", "yesterday", "this week", "last week", "this month"):
        if re.search(rf"\b{word}\b", t):
            return word
    return None


def _list_status(t: str, kind: str | None) -> str | None:
    if re.search(r"\broll(?:ed)?[\s-]?back\b", t):
        return "ROLLED_BACK"
    if re.search(r"\b(?:fail\w*|broken|errors?)\b", t) and kind != "AWS_ISSUE":
        return "COMPLETED_FAILED"
    if re.search(r"\b(?:success\w*|succeeded|completed|deployed|done|live)\b", t) and kind != "AWS_ISSUE":
        return "COMPLETED_SUCCESS"
    if re.search(r"\bin[\s-]?progress\b|\bongoing\b|\brunning\b|\bstarted\b", t):
        return "IN_PROGRESS"
    if re.search(r"\bapproved\b", t):
        return "APPROVED"
    if re.search(r"\b(?:rejected|declined|denied)\b", t):
        return "REJECTED"
    if re.search(r"\baccess (?:given|granted)\b|\bgranted\b|\bgiven\b", t):
        return "ACCESS_GIVEN"
    if re.search(r"\b(?:resolved|closed|fixed)\b", t):
        return "RESOLVED"
    if kind == "AWS_ISSUE" and re.search(r"\bopen\b|\bunresolved\b|\bnew\b|\bpending\b", t):
        return "OPEN"
    if re.search(r"\b(?:pending|requested|waiting|new|unapproved)\b", t):
        return "REQUESTED"
    return None


_VERB_STATUS = {
    "approve": "APPROVED", "reject": "REJECTED", "decline": "REJECTED", "deny": "REJECTED",
    "start": "IN_PROGRESS", "begin": "IN_PROGRESS", "rollback": "ROLLED_BACK", "roll back": "ROLLED_BACK",
    "revert": "ROLLED_BACK", "complete": "COMPLETED_SUCCESS", "grant": "ACCESS_GIVEN",
}
_MARK_STATUS = [
    (r"\broll(?:ed)?[\s-]?back\b", "ROLLED_BACK"),
    (r"\bfail\w*\b", "COMPLETED_FAILED"),
    (r"\b(?:success\w*|succeeded|completed|deployed|done)\b", "COMPLETED_SUCCESS"),
    (r"\bin[\s-]?progress\b|\bstarted\b|\brunning\b", "IN_PROGRESS"),
    (r"\bapproved\b", "APPROVED"),
    (r"\b(?:rejected|declined)\b", "REJECTED"),
    (r"\b(?:given|granted)\b", "ACCESS_GIVEN"),
]


def _status_change(t: str, has_number: bool) -> tuple[str, str] | None:
    """-> (new_status, verb text) or None."""
    if _LISTY.match(t):
        return None
    first = t.split(" ", 1)[0]
    m = re.search(r"\b(approve|reject|decline|deny|start|begin|rollback|roll back|revert|complete|grant)\b", t)
    if m and (has_number or first == m.group(1).split(" ")[0]):
        verb = m.group(1)
        return _VERB_STATUS[verb], verb
    if re.search(r"\b(?:mark|set|update|change|move|flag)\b", t) and (has_number or first in ("mark", "set", "update", "change", "move", "flag")):
        for pattern, status in _MARK_STATUS:
            if re.search(pattern, t):
                return status, "mark"
    return None


_QUESTION = re.compile(r"^(?:who|whom|whose|when|what|what's|whats|which|why|where|is|was|has|have|did|does|do|"
                       r"tell me|give me (?:the )?details|details|describe|explain)\b")
_PRONOUN = re.compile(r"\b(?:it|its|it's|this|that|this one|that one|same one|the same|current one)\b")
_OPEN_VERB = re.compile(r"^(?:open|show|view|display|go to|take me to|bring up|pull up)\b")
_PLURAL = re.compile(r"\b(?:deployments|requests|issues|applications|incidents|accesses|ones|any|all|every|there)\b")
_ASK_FIELDS = [
    ("assignee", r"\bwho\b.*\b(?:assigned|handling|handles|working|owns?|owner|responsible|deploying|doing)\b|\bassignee\b|\bassigned to\b"),
    ("requester", r"\bwho\b.*\b(?:request\w*|raised?|creat\w*|asked|submit\w*|made|opened|reported|filed)\b|\brequester\b|\braised by\b"),
    ("reason", r"\bwhy\b|\breason\b|\bcause\b"),
    ("time", r"\bwhen\b|\bwhat time\b|\bschedul\w*\b|\bdate\b"),
    ("branch", r"\bbranch\b"),
    ("environment", r"\benvironment\b|\bwhich env\b"),
    ("project", r"\b(?:application|project|which app)\b"),
    ("status", r"\bstatus\b|\bstate\b|\b(?:approved|rejected|done|completed|finished|deployed|failed|resolved|"
               r"in progress|pending|given|granted|rolled back)\b"),
]


def _ask_field(t: str) -> str | None:
    for name, pattern in _ASK_FIELDS:
        if re.search(pattern, t):
            return name
    return None


def split_ref(ref) -> tuple[str, str] | tuple[None, None]:
    """'DEP-000123' -> ('DEPLOYMENT', '123')."""
    m = re.match(r"^(DEP|ACC|AWS)-0*(\d+)$", str(ref or "").strip().upper())
    if not m:
        return None, None
    kind = {"DEP": "DEPLOYMENT", "ACC": "ACCESS", "AWS": "AWS_ISSUE"}[m.group(1)]
    return kind, m.group(2) or "0"


def parse(t: str, apps: list[str], ref: str | None = None) -> dict:
    """Understand an already-normalized sentence. Returns a plan dict.
    `ref` is the record the user is looking at / last talked about ("it", "this one")."""
    if not t:
        return {"intent": "wake"}
    if _DISMISS.match(t):
        return {"intent": "dismiss"}
    if _GREET.match(t):
        return {"intent": "greet"}
    if re.match(r"^how are you\b", t):
        return {"intent": "reply", "text": "I'm doing great, thank you! How can I help you?"}
    if _HELP.match(t):
        return {"intent": "help"}
    if _WHOAMI.search(t):
        return {"intent": "whoami"}
    if _LOGOUT.search(t):
        return {"intent": "logout"}
    if _BACK.match(t):
        return {"intent": "back"}

    kind = _kind(t)
    scrubbed = re.sub(r"\b(?:top|last|first|latest|recent|next)\s+\d+\b", " ", t)
    m = re.search(r"\b(\d{1,12})\b", scrubbed)
    number = m.group(1) if m else None

    # --- context: "it" / "this one" / no number -> the record on screen or last talked about
    ref_kind, ref_num = split_ref(ref)
    ref_ok = bool(ref_kind) and not number and (kind is None or kind == ref_kind) and not _PLURAL.search(t)
    pronoun = bool(_PRONOUN.search(t))

    if not number and re.match(r"^(?:deploy|release|push)\b", t):
        return {"intent": "create", "kind": "DEPLOYMENT"}
    if re.match(r"^(?:(?:get|give|grant) me|i need|need|i want|want|request|requesting)\s+(?:an?\s+)?access\b", t):
        return {"intent": "create", "kind": "ACCESS"}

    change = _status_change(t, bool(number))
    if change:
        new_status, verb = change
        if new_status == "ACCESS_GIVEN":
            kind = "ACCESS"
        if not number and ref_ok and (kind is None or kind == ref_kind) and (new_status != "ACCESS_GIVEN" or ref_kind == "ACCESS"):
            return {"intent": "status_change", "kind": ref_kind, "number": ref_num, "new_status": new_status}
        kind = kind or "DEPLOYMENT"
        if not number:
            return {"intent": "clarify", "carry": t, "kind": kind, "new_status": new_status, "verb": verb}
        return {"intent": "status_change", "kind": kind, "number": number, "new_status": new_status}

    plural = re.search(r"\b(?:deployments|requests|issues|applications|incidents)\b", t)
    if _CREATE.match(t) and not number and not (t.startswith("new ") and plural):
        if re.search(r"\bapplications?\b|\bapp\b", t):
            return {"intent": "create", "kind": "APPLICATION"}
        if kind:
            return {"intent": "create", "kind": kind}
        return {"intent": "clarify", "carry": "create", "kind": None, "new_status": None, "verb": "create"}

    if _COUNT.search(t) and not number:
        return _list_plan(t, kind, apps, count_only=True)

    # questions about ONE record: "who requested deployment 12", "when is it scheduled", "why did it fail"
    if _QUESTION.match(t) and not _PLURAL.search(t):
        field = _ask_field(t)
        if number and (kind or field):
            return {"intent": "ask", "kind": kind, "number": number, "field": field}
        if ref_ok and (pronoun or (field and kind is None)):
            return {"intent": "ask", "kind": ref_kind, "number": ref_num, "field": field}

    # "open it", "show this one"
    if ref_ok and pronoun and _OPEN_VERB.match(t):
        return {"intent": "open", "kind": ref_kind, "number": ref_num}

    if number and (kind or re.match(r"^(?:open|show|go to|view|find|get|details|status|check)\b", t) or t == number):
        return {"intent": "open", "kind": kind, "number": number}

    s = _SEARCH.match(t)
    if s:
        term = s.group(1).strip()
        if not (_kind(term) or _list_status(term, None) or _env(term) or _date(term)):
            return {"intent": "search", "term": term}

    if _SUMMARY.search(t) and not kind:
        return {"intent": "summary"}

    if not kind:
        page = None
        if re.search(r"\b(?:dashboard|home(?: page)?|main page)\b", t):
            page = "dashboard"
        elif re.search(r"\b(?:profile|my account|account settings|settings|preferences)\b", t):
            page = "profile"
        elif re.search(r"\b(?:user management|users|team members)\b", t):
            page = "users"
        elif re.search(r"\bapplications?\b", t):
            page = "applications"
        if page:
            return {"intent": "navigate", "page": page}

    if kind or _list_status(t, kind) or _env(t) or _project(t, apps) or _date(t):
        return _list_plan(t, kind, apps)

    return {"intent": "unknown"}


def _list_plan(t: str, kind: str | None, apps: list[str], count_only: bool = False) -> dict:
    return {
        "intent": "count" if count_only else "list",
        "kind": kind or "DEPLOYMENT",
        "status": _list_status(t, kind),
        "env": _env(t),
        "project": _project(t, apps),
        "date": _date(t),
        "mine": bool(re.search(r"\b(?:my|mine|i raised|i created|i requested)\b", t)),
    }


# ---------------------------------------------------------------------
# Voice edits / reassignment (rules) - raw text is needed for branch names
# ---------------------------------------------------------------------

# Deployment details a DevOps user may change by voice (never files / env-var secrets).
VOICE_EDITABLE = {
    "rollbackBranch": "rollback branch", "additionalInfo": "additional info",
    "dbChange": "database change flag", "dbChangeDetails": "database change details",
    "thirdPartyApiChange": "third-party API change flag", "thirdPartyApiDetails": "third-party API details",
}

_EDIT_RE = re.compile(
    r"^(?:please\s+)?(?:set|change|update|make|put)\s+(?:the\s+)?rollback\s+branch\s*"
    r"(?:(?:of|for|on|in)\s+(?:(?:the\s+)?(?:deployment|dep)\s*)?(?P<num>\d+|it|this(?: one)?|that(?: one)?)\s*)?"
    r"(?:to|as|=)\s+(?P<val>.+?)\s*[.!?]?$", re.I)
_ASSIGN_RE = re.compile(
    r"^(?:re-?assign|assign|give|hand(?: over)?)\s+(?:the\s+)?(?:(?:deployment|dep)\s*)?(?P<num>\d+|it|this(?: one)?|that(?: one)?)?"
    r"\s*(?:to|for)\s+(?P<who>[a-z][a-z .'-]*?)\s*$")


def _special(raw: str, t: str, ref: str | None) -> dict | None:
    """Rule plans that need the raw text (branch names keep '/', '.', '-')."""
    from .voice_form import spoken_symbols
    rk, rn = split_ref(ref)
    text = re.sub(r"^\s*(?:hello|helo|hullo|hallo|hey|hay|ok|okay)\s+(?:ops ?flow|ops)\b[\s,]*", "", str(raw or ""), flags=re.I)
    m = _EDIT_RE.match(text.strip())
    if m:
        num = m.group("num")
        if num and num.isdigit():
            number = num
        elif rk == "DEPLOYMENT":
            number = rn
        else:
            return {"intent": "clarify", "carry": t, "kind": "DEPLOYMENT", "new_status": None, "verb": "update"}
        value = spoken_symbols(m.group("val")).strip(" '\"")
        return {"intent": "edit", "kind": "DEPLOYMENT", "number": number, "fields": {"rollbackBranch": value}}
    m = _ASSIGN_RE.match(t)
    if m and (m.group("num") or rk == "DEPLOYMENT"):
        num = m.group("num")
        number = num if num and num.isdigit() else (rn if rk == "DEPLOYMENT" else None)
        if number:
            return {"intent": "reassign", "kind": "DEPLOYMENT", "number": number, "who": m.group("who").strip()}
    return None


# ---------------------------------------------------------------------
# The AI agent (Claude): understands anything, looks things up, then acts
# ---------------------------------------------------------------------

_STATUSES = list(STATUS_SPOKEN)
_DATES = ["today", "tomorrow", "yesterday", "this week", "last week", "this month"]
_REC = {"type": "string", "description": "record id like DEP-000123 / ACC-000007 / AWS-000002, or just the number"}
_KIND = {"type": "string", "enum": list(KINDS)}
_FILTERS = {
    "kind": _KIND,
    "status": {"type": "string", "enum": _STATUSES},
    "environment": {"type": "string", "enum": list(ENVIRONMENTS)},
    "project": {"type": "string", "description": "application name"},
    "date": {"type": "string", "enum": _DATES},
    "mine": {"type": "boolean", "description": "only records the current user raised"},
    "requested_by": {"type": "string", "description": "name of the person who raised them"},
}

READ_TOOLS = {"get_record", "find_records", "search_records"}
AGENT_TOOLS = [
    # ---- look-ups (read-only; the agent sees the result and continues) ----
    {"name": "get_record", "description": "Read one record's full details (status, dates, people, branches, reasons).",
     "input_schema": {"type": "object", "properties": {"record": _REC, "kind": _KIND}, "required": ["record"]}},
    {"name": "find_records", "description": "Find / count records with filters. Returns the count and the latest 10.",
     "input_schema": {"type": "object", "properties": _FILTERS, "required": ["kind"]}},
    {"name": "search_records", "description": "Free-text search over all records (names, apps, messages, branches).",
     "input_schema": {"type": "object", "properties": {"term": {"type": "string"}}, "required": ["term"]}},
    # ---- final actions (exactly one ends the turn) ----
    {"name": "answer", "description": "Speak an answer to the user. Use ONLY facts from look-up results or the "
     "conversation. 1-2 short spoken sentences, no markdown. Also for greetings, small talk, how-to questions and "
     "explaining that something is not allowed.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "record_ids": {"type": "array", "items": {"type": "string"}, "description": "records to show as cards"},
         "open": {"type": "boolean", "description": "also open the (single) record on screen"}}, "required": ["text"]}},
    {"name": "open_record", "description": "Open one record on screen.",
     "input_schema": {"type": "object", "properties": {"record": _REC, "kind": _KIND}, "required": ["record"]}},
    {"name": "show_records", "description": "Show (or just count) a filtered list on screen and read the result.",
     "input_schema": {"type": "object", "properties": {**_FILTERS, "count_only": {"type": "boolean"}},
                      "required": ["kind"]}},
    {"name": "navigate", "description": "Go to a page.",
     "input_schema": {"type": "object", "properties": {"page": {"type": "string", "enum": [
         "dashboard", "deployments", "access", "aws-issues", "profile", "users", "applications"]}}, "required": ["page"]}},
    {"name": "go_back", "description": "Go back to the previous page.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "create_record", "description": "Open the form for a new record; the assistant then fills it by voice.",
     "input_schema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": list(KINDS) + ["APPLICATION"]}}, "required": ["kind"]}},
    {"name": "change_status", "description": "Change the status of a deployment or access request. The user is "
     "asked to confirm (and for a reason when rejecting / failing / rolling back).",
     "input_schema": {"type": "object", "properties": {
         "record": _REC, "kind": {"type": "string", "enum": ["DEPLOYMENT", "ACCESS"]},
         "new_status": {"type": "string", "enum": ["APPROVED", "REJECTED", "IN_PROGRESS", "COMPLETED_SUCCESS",
                                                   "COMPLETED_FAILED", "ROLLED_BACK", "ACCESS_GIVEN"]}},
         "required": ["record", "new_status"]}},
    {"name": "edit_deployment", "description": "Change details of a deployment (DevOps only; user confirms). "
     "Only the fields given are changed.",
     "input_schema": {"type": "object", "properties": {
         "record": _REC, "rollbackBranch": {"type": "string"}, "additionalInfo": {"type": "string"},
         "dbChange": {"type": "boolean"}, "dbChangeDetails": {"type": "string"},
         "thirdPartyApiChange": {"type": "boolean"}, "thirdPartyApiDetails": {"type": "string"}},
         "required": ["record"]}},
    {"name": "assign_deployment", "description": "Assign a deployment to a DevOps engineer (admin only; user confirms).",
     "input_schema": {"type": "object", "properties": {
         "record": _REC, "devops_name": {"type": "string", "description": "person's name, or 'me'"}},
         "required": ["record", "devops_name"]}},
    {"name": "summary", "description": "Overview: how many records are in each status.",
     "input_schema": {"type": "object", "properties": {}}},
]
_FINAL_TOOLS = [t for t in AGENT_TOOLS if t["name"] not in READ_TOOLS]


def _rec_parts(value, kind=None) -> tuple[str | None, str]:
    k, n = split_ref(value)
    if k:
        return k, n
    s = str(value or "")
    k = _kind(s.lower()) or kind
    digits = re.sub(r"\D", "", s)
    return k, (str(int(digits)) if digits else "")


def _filters_from(a: dict, names: dict) -> dict:
    by = None
    who = str(a.get("requested_by") or "").strip()
    if who:
        by = [uid for uid, n in names.items() if _name_match(who, n)] or ["__nobody__"]
    return {"intent": "count" if a.get("count_only") else "list", "kind": a.get("kind") or "DEPLOYMENT",
            "status": a.get("status"), "env": a.get("environment"), "project": a.get("project"),
            "date": a.get("date") if a.get("date") in _DATES else None, "mine": bool(a.get("mine")), "by": by,
            "by_name": who or None}


def _plan_from_agent(name: str, a: dict, names: dict) -> dict | None:
    if name == "answer":
        return {"intent": "answer", "text": str(a.get("text") or "")[:400],
                "ids": [str(x) for x in (a.get("record_ids") or [])][:8], "open": bool(a.get("open"))}
    if name == "open_record":
        k, n = _rec_parts(a.get("record"), a.get("kind"))
        return {"intent": "open", "kind": k, "number": n}
    if name == "show_records":
        return _filters_from(a, names)
    if name == "navigate":
        return {"intent": "navigate", "page": a.get("page")}
    if name == "go_back":
        return {"intent": "back"}
    if name == "create_record":
        return {"intent": "create", "kind": a.get("kind")}
    if name == "change_status":
        k, n = _rec_parts(a.get("record"), a.get("kind"))
        return {"intent": "status_change", "kind": k or "DEPLOYMENT", "number": n, "new_status": a.get("new_status")}
    if name == "edit_deployment":
        _, n = _rec_parts(a.get("record"), "DEPLOYMENT")
        fields = {k: a[k] for k in VOICE_EDITABLE if k in a and a[k] is not None}
        return {"intent": "edit", "kind": "DEPLOYMENT", "number": n, "fields": fields}
    if name == "assign_deployment":
        _, n = _rec_parts(a.get("record"), "DEPLOYMENT")
        return {"intent": "reassign", "kind": "DEPLOYMENT", "number": n, "who": str(a.get("devops_name") or "")}
    if name == "summary":
        return {"intent": "summary"}
    return None


_SECRET_KEYS = {"DBChangeFileData", "Attachments", "EnvVarDetails", "Deleted", "DeletedBy", "DeletedAt", "Record Type"}


def _brief(rec: dict, names: dict) -> dict:
    """What the model may see about a record: no files, no env-var secrets, short texts, names not ids."""
    out = {}
    for k, v in rec.items():
        if k in _SECRET_KEYS or v in (None, "", False):
            continue
        if k in ("DateTime", "CreatedAt", "UpdatedAt", "ResolvedAt"):
            d = _parse_iso(v)
            v = d.astimezone(_tz()).strftime("%a %d %b %Y %I:%M %p") if d else v
        if k in ("RequesterID", "AssignedDevOpsID"):
            out[k.replace("ID", "")] = names.get(v, v)
            continue
        out[k] = v[:300] if isinstance(v, str) else v
    out["StatusLabel"] = logic._label(rec.get("Status"))
    return out


def _run_read(db: Session, ctx: Ctx, user, name: str, a: dict, names: dict) -> dict:
    try:
        if name == "get_record":
            k, n = _rec_parts(a.get("record"), a.get("kind"))
            if not n:
                return {"error": "no record number given"}
            found = _find_one(db, user, k, n)
            if not found:
                return {"error": "not found (or not visible to this user)"}
            return {"records": [_brief(logic._to_dict(o, kk), names) for kk, o in found]}
        if name == "find_records":
            plan = _filters_from(a, names)
            if not logic.can_view_record(user, plan["kind"]):
                return {"error": "this user cannot see that kind of record"}
            rows = _fetch(db, ctx, user, plan["kind"], plan)
            return {"count": len(rows), "latest": [_brief(logic._to_dict(r, plan["kind"]), names) for r in rows[:10]]}
        if name == "search_records":
            rows = logic.handle_search(db, str(a.get("term") or ""), ctx)
            return {"count": len(rows), "results": [_brief(r, names) for r in rows[:10]]}
    except ApiError as e:
        return {"error": str(e)}
    return {"error": "unknown tool"}


def _history_messages(history) -> list[dict]:
    msgs: list[dict] = []
    for h in (history or [])[-6:]:
        if not isinstance(h, dict):
            continue
        role = "assistant" if h.get("role") == "assistant" else "user"
        text = str(h.get("text") or "").strip()[:400]
        if not text:
            continue
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += " / " + text
        else:
            msgs.append({"role": role, "content": text})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    while msgs and msgs[-1]["role"] == "user":     # the current sentence is appended by the caller
        msgs.pop()
    return msgs


def _agent_system(user, apps: list[str], ref: str | None, page: str) -> str:
    admin = is_admin(user)
    rk, rn = split_ref(ref)
    on_screen = f"{KIND_LABEL[rk]} {rn} ({ref})" if rk else "none"
    now = datetime.now(_tz())
    return (
        "You are OPS, the smart voice assistant inside OPSFlow, a tool where Dev, QA and DevOps teams track "
        "deployment requests, access requests and AWS issues. The user speaks; speech-to-text can mishear words "
        "(e.g. 'deploy meant' = deployment, numbers as words). Work out what they MEAN, like a smart colleague.\n"
        "How to work: if you need facts, call get_record / find_records / search_records first (you may call "
        "several). Then end with exactly ONE action tool. Prefer doing over asking: if the request is clear enough, "
        "act. If it is truly ambiguous, use answer to ask one short question.\n"
        "Rules: never invent records, names, numbers or dates; state data only from look-up results. Answers are "
        "spoken aloud: 1-2 short sentences, no markdown, no lists of IDs; say 'deployment 123' not 'DEP-000123'. "
        "Status changes, edits and assignments are confirmed by the user afterwards, so just choose them.\n"
        "IDs: DEP-000123 = deployment 123, ACC-000007 = access request 7, AWS-000002 = AWS issue 2. "
        f"'it', 'this', 'that one' = the record in focus: {on_screen}. Current page: {page or '/'}.\n"
        f"Permissions of this user ({user.name}, role {user.role}{', admin' if admin else ''}): "
        "only DevOps change statuses and edit deployment details; only Developers and QA raise deployment "
        "requests; anyone can request access; only DevOps see and report AWS issues; only admins assign "
        "deployments, manage users and applications. If something is not allowed, say so briefly with answer.\n"
        f"Applications: {', '.join(apps)}. Environments: DEV, QA, UAT, PROD. Statuses: REQUESTED (pending), "
        "APPROVED, REJECTED, IN_PROGRESS, COMPLETED_SUCCESS, COMPLETED_FAILED, ROLLED_BACK, ACCESS_GIVEN, OPEN, RESOLVED.\n"
        f"Now: {now:%A %d %B %Y, %I:%M %p} (India time)."
    )


def agent_plan(db: Session, ctx: Ctx, user, raw: str, apps: list[str], history, ref: str | None,
               page: str, max_steps: int = 2, budget: float = 4.0) -> dict | None:
    """Claude decides. Read-only look-ups run here and are fed back; returns a plan or None."""
    if not llm.enabled():
        return None
    names = _user_names(db)
    system = _agent_system(user, apps, ref, page)
    messages = _history_messages(history) + [{"role": "user", "content": raw}]
    deadline = time.monotonic() + budget      # SPEED: never make the user wait more than ~4 s for the AI
    for step in range(max_steps):
        left = deadline - time.monotonic()
        if left < 0.8:
            return None                       # too late: the rule-based answer is used instead
        last = step == max_steps - 1
        data = llm.call({"model": llm.model(), "max_tokens": 300, "system": system,
                         "tools": _FINAL_TOOLS if last else AGENT_TOOLS, "tool_choice": {"type": "any"},
                         "messages": messages}, timeout=min(4.0, left))
        uses = llm.tool_uses(data)
        if not uses:
            return None
        final = next((u for u in uses if u.get("name") not in READ_TOOLS), None)
        if final:
            return _plan_from_agent(final.get("name", ""), final.get("input") or {}, names)
        messages.append({"role": "assistant", "content": data["content"]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": u["id"],
             "content": json.dumps(_run_read(db, ctx, user, u["name"], u.get("input") or {}, names), default=str)[:6000]}
            for u in uses]})
    return None


# ---------------------------------------------------------------------
# Executing a plan
# ---------------------------------------------------------------------

def _say(speech: str, intent: str = "reply", **extra) -> dict:
    return {"intent": intent, "speech": speech, **extra}


def _num(record_id: str) -> str:
    try:
        return str(int(str(record_id).split("-")[1]))
    except (IndexError, ValueError):
        return str(record_id)


def _short(kind: str, record_id: str) -> str:
    return f"{KIND_LABEL[kind]} {_num(record_id)}"


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(settings.MAIL_TIMEZONE)
    except Exception:
        return timezone(timedelta(hours=5, minutes=30))


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _range(word: str) -> tuple[datetime, datetime]:
    tz = _tz()
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    if word == "today":
        return today, today + timedelta(days=1)
    if word == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=2)
    if word == "yesterday":
        return today - timedelta(days=1), today
    if word == "this week":
        return monday, monday + timedelta(days=7)
    if word == "last week":
        return monday - timedelta(days=7), monday
    first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt


def _squash(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _aware(d):
    if d is None:
        return None
    if isinstance(d, str):
        return _parse_iso(d)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _obj_matches(obj, f: dict) -> bool:
    if f.get("project") and _squash(f["project"]) not in _squash(getattr(obj, "project", "")):
        return False
    if f.get("date"):
        when = _aware(getattr(obj, "date_time", None) or getattr(obj, "created_at", None))
        lo, hi = _range(f["date"])
        if not when or not (lo <= when.astimezone(lo.tzinfo) < hi):
            return False
    return True


def _item(rec: dict) -> dict:
    kind = rec["Record Type"]
    rid = rec["Record ID"]
    if kind == "DEPLOYMENT":
        title = " · ".join(x for x in (rec.get("Project"), rec.get("Component")) if x) or "Deployment"
        when = _parse_iso(rec.get("DateTime"))
        sub = " · ".join(x for x in (rec.get("Environment"), when.astimezone(_tz()).strftime("%d %b, %I:%M %p") if when else "") if x)
    elif kind == "ACCESS":
        title = " · ".join(x for x in (rec.get("AccessType"), rec.get("Project")) if x) or "Access request"
        sub = " · ".join(x for x in (rec.get("Environment"), rec.get("UserResource")) if x)
    else:
        title = " · ".join(x for x in (rec.get("Service"), rec.get("Project")) if x) or "AWS issue"
        sub = (rec.get("ErrorMessage") or "")[:80]
    return {"id": rid, "type": kind, "title": title, "subtitle": sub, "status": rec.get("Status"),
            "statusLabel": logic._label(rec.get("Status")), "route": f"{KIND_ROUTE[kind]}/{rid}"}


def _fetch(db: Session, ctx: Ctx, user, kind: str, f: dict) -> list:
    """Matching records (ORM objects, newest first). Filters run in SQL where possible and
    only the few records that are shown are serialized (faster than listing everything)."""
    if not logic.can_view_record(user, kind):
        raise ApiError("AWS issues are only available to DevOps users.")
    model = logic._MODEL_BY_TYPE[kind]
    q = logic.light_query(db, model)
    if hasattr(model, "deleted"):
        q = q.filter(model.deleted.is_(False))
    if f.get("status"):
        q = q.filter(model.status == f["status"])
    if f.get("mine") or not logic.sees_all_records(user):
        q = q.filter(model.requester_id == user.id)   # Developer / QA: only their own requests
    if f.get("by"):
        q = q.filter(model.requester_id.in_(list(f["by"])))
    if f.get("env"):
        q = q.filter(func.upper(model.environment) == str(f["env"]).upper())
    rows = q.order_by(model.created_at.desc()).all()
    return [r for r in rows if _obj_matches(r, f)]


def _phrase(kind: str, f: dict) -> str:
    bits = []
    if f.get("mine"):
        bits.append("your")
    if f.get("status"):
        bits.append(STATUS_SPOKEN.get(f["status"], ""))
    bits.append(KIND_PLURAL[kind])
    if f.get("env"):
        bits.append(f"in {f['env']}")
    if f.get("project"):
        bits.append(f"for {f['project']}")
    if f.get("date"):
        bits.append(f["date"])
    if f.get("by_name"):
        bits.append(f"raised by {f['by_name']}")
    return " ".join(b for b in bits if b)


def _find_one(db: Session, user, kind: str | None, number: str):
    found = []
    for k in ([kind] if kind else KINDS):
        obj, _ = logic.find_record(db, f"{KIND_PREFIX[k]}-{int(number):06d}")
        if obj and not getattr(obj, "deleted", False) and logic.can_view_item(user, k, obj):
            found.append((k, obj))
    return found


def _user_names(db: Session) -> dict:
    return {u.id: u.name for u in db.query(User.id, User.name).all()}


def _name_match(spoken: str, name: str) -> bool:
    a, b = _squash(spoken), _squash(name)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    first = _squash(str(name).split(" ")[0])
    return difflib.SequenceMatcher(None, a, first).ratio() >= 0.75 or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def _when(d) -> str:
    d = _aware(d)
    if not d:
        return ""
    local = d.astimezone(_tz())
    today = datetime.now(_tz()).date()
    day = ("today" if local.date() == today else "tomorrow" if local.date() == today + timedelta(days=1)
           else "yesterday" if local.date() == today - timedelta(days=1) else local.strftime("%A %d %B"))
    return f"{day} at {local.strftime('%I:%M %p').lstrip('0')}"


def _answer_about(db: Session, kind: str, obj, field: str | None) -> str:
    """Spoken answer to a question about one record, from the real data."""
    names = _user_names(db)
    name = _short(kind, obj.id)
    Name = name[0].upper() + name[1:]
    status = logic._label(obj.status).lower()
    requester = names.get(obj.requester_id, "someone")
    assignee = names.get(getattr(obj, "assigned_devops_id", None) or "", "")
    when = _when(getattr(obj, "date_time", None))
    raised = _when(obj.created_at)

    if field == "requester":
        return f"{Name} was raised by {requester}" + (f", {raised}." if raised else ".")
    if field == "assignee":
        if kind != "DEPLOYMENT":
            return f"{Name} is not assigned to a person. It is {status}."
        return f"{Name} is assigned to {assignee}." if assignee else f"{Name} is not assigned to anyone yet."
    if field == "time":
        if when:
            return f"{Name} is {'scheduled for' if kind == 'DEPLOYMENT' else 'from'} {when}. It is {status}."
        return f"{Name} was raised {raised}. It is {status}."
    if field == "reason":
        reason = (getattr(obj, "failure_reason", None) or getattr(obj, "rollback_reason", None)
                  or getattr(obj, "rejection_reason", None) or getattr(obj, "root_cause", None)
                  or getattr(obj, "reason", None) or "")
        return f"{Name} is {status}. The reason given: {reason}." if reason else f"{Name} is {status}. No reason was recorded."
    if field == "branch" and kind == "DEPLOYMENT":
        rb = f", and the rollback branch is {obj.rollback_branch}" if obj.rollback_branch else ""
        return f"{Name} deploys branch {obj.github_branch or 'not given'}{rb}."
    if field == "environment":
        return f"{Name} is for {obj.environment or 'no environment'}."
    if field == "project":
        return f"{Name} is for {obj.project or 'no application'}."
    if field == "status":
        return f"{Name} is {status}."
    # general description
    bits = [f"{Name} is {status}"]
    if kind == "DEPLOYMENT":
        bits.append(f"{obj.project or ''} {obj.component or ''} to {obj.environment or ''}".strip())
        if when:
            bits.append(f"scheduled {when}")
        if assignee:
            bits.append(f"assigned to {assignee}")
    elif kind == "ACCESS":
        bits.append(f"{obj.access_type or ''} access for {obj.project or ''} {obj.environment or ''}".strip())
    else:
        bits.append(f"{obj.service or 'AWS'} issue on {obj.project or ''}, priority {obj.priority or 'not set'}")
    bits.append(f"raised by {requester}")
    return ", ".join(b for b in bits if b) + "."


def _execute(db: Session, ctx: Ctx, user, plan: dict, t: str) -> dict:
    intent = plan.get("intent")
    first = (user.name or "there").split(" ")[0]

    if intent == "wake":
        return _say("Yes, I'm listening.", "wake")
    if intent == "greet":
        return _say(f"Hi {first}! What can I do for you?", "greet")
    if intent == "reply":
        return _say(plan.get("text") or "How can I help you?")
    if intent == "dismiss":
        return _say("Okay. Say Hello Ops whenever you need me.", "dismiss")
    if intent == "back":
        return _say("Going back.", "back")
    if intent == "logout":
        return _say("Signing you out. Goodbye!", "logout")
    if intent == "whoami":
        role = f"{user.role}{' admin' if is_admin(user) else ''}"
        return _say(f"You are {user.name}, {role}.")
    if intent == "help":
        return _say("You can say: open deployment 123. Show failed deployments. How many pending access requests? "
                    "Show prod deployments today. Approve deployment 123. Create a new deployment. Or search for any project.",
                    "help", examples=EXAMPLES)

    if intent == "clarify":
        if plan.get("kind") is None and plan.get("verb") == "create":
            return _say("What would you like to create: a deployment, an access request or an AWS issue?",
                        "clarify", carry=plan["carry"])
        return _say(f"Which {KIND_LABEL[plan['kind']]} number should I {plan.get('verb', 'update')}?",
                    "clarify", carry=plan["carry"])

    if intent == "navigate":
        page = plan.get("page")
        routes = {"dashboard": ("/", "the dashboard"), "profile": ("/profile", "your profile"),
                  "users": ("/users", "user management"), "applications": ("/applications", "applications"),
                  "deployments": ("/deployments", "deployments"), "access": ("/access", "access requests"),
                  "aws-issues": ("/aws-issues", "AWS issues")}
        if page not in routes:
            return _say("Sorry, I don't know that page.", "error")
        if page in ("users", "applications") and not is_admin(user):
            return _say("That page is only for DevOps admins.", "error")
        if page == "aws-issues" and not logic.can_view_record(user, "AWS_ISSUE"):
            return _say("AWS issues are only available to DevOps users.", "error")
        route, label = routes[page]
        return _say(f"Opening {label}.", "navigate", route=route)

    if intent == "create":
        kind = plan.get("kind")
        # The browser opens the real form, then the conversation continues through the voiceForm action
        # (voice_form.py), which asks for each value and fills the form on screen. The user submits.
        if kind == "DEPLOYMENT":
            if user.role not in ("Developer", "QA"):
                return _say("Only Developers and QA can raise deployment requests.", "error")
            return _say("Opening a new deployment request.", "form_start", formKind="DEPLOYMENT", route="/deployments?new=1")
        if kind == "ACCESS":
            return _say("Opening a new access request.", "form_start", formKind="ACCESS", route="/access?new=1")
        if kind == "AWS_ISSUE":
            if user.role != "DevOps":
                return _say("Only DevOps users can report AWS issues.", "error")
            return _say("Opening a new AWS issue.", "form_start", formKind="AWS_ISSUE", route="/aws-issues?new=1")
        if kind == "APPLICATION":
            if not is_admin(user):
                return _say("Only DevOps admins can add applications.", "error")
            return _say("Opening the applications page.", "form_start", formKind="APPLICATION", route="/applications?new=1")
        return _say("I can create deployments, access requests or AWS issues. Which one?", "clarify", carry="create")

    if intent == "open":
        number = str(plan.get("number") or "")
        if not number:
            return _say("Which number should I open?", "clarify", carry=t)
        found = _find_one(db, user, plan.get("kind"), number)
        if not found:
            what = KIND_LABEL[plan["kind"]] if plan.get("kind") else "record"
            return _say(f"I couldn't find {what} {int(number)}.", "error")
        if len(found) > 1:
            items = [_item(logic._to_dict(o, k)) for k, o in found]
            return _say(f"Number {int(number)} exists as more than one record. Which one do you want?",
                        "list", results=items)
        k, obj = found[0]
        item = _item(logic._to_dict(obj, k))
        return _say(f"Opening {_short(k, obj.id)}. It's {item['statusLabel'].lower()}"
                    f"{', ' + (obj.project or '') if getattr(obj, 'project', None) else ''}.",
                    "open", route=item["route"], results=[item], focus=obj.id)

    if intent == "ask":
        number = str(plan.get("number") or "")
        found = _find_one(db, user, plan.get("kind"), number) if number else []
        if not found:
            what = KIND_LABEL[plan["kind"]] if plan.get("kind") else "record"
            return _say(f"I couldn't find {what} {int(number or 0)}.", "error")
        if len(found) > 1:
            items = [_item(logic._to_dict(o, k)) for k, o in found]
            return _say(f"Number {int(number)} exists as more than one record. Which one do you mean?", "list", results=items)
        k, obj = found[0]
        item = _item(logic._to_dict(obj, k))
        return _say(_answer_about(db, k, obj, plan.get("field")), "answer", results=[item], focus=obj.id)

    if intent == "answer":
        items = []
        for rid in plan.get("ids") or []:
            k, n = _rec_parts(rid)
            if k and n:
                for kk, o in _find_one(db, user, k, n):
                    items.append(_item(logic._to_dict(o, kk)))
        out = _say(plan.get("text") or "Okay.", "answer", results=items or None)
        if plan.get("open") and len(items) == 1:
            out["route"] = items[0]["route"]
        if len(items) == 1:
            out["focus"] = items[0]["id"]
        return out

    if intent == "edit":
        number = str(plan.get("number") or "")
        if user.role != "DevOps":
            return _say("Only DevOps users can change deployment details.", "error")
        fields = {k: v for k, v in (plan.get("fields") or {}).items() if k in VOICE_EDITABLE}
        if not fields:
            return _say("What should I change? For example: set the rollback branch to release 1.0.", "clarify",
                        carry=t)
        found = _find_one(db, user, "DEPLOYMENT", number) if number else []
        if not found:
            return _say(f"I couldn't find deployment {int(number or 0)}.", "error")
        obj = found[0][1]
        name = _short("DEPLOYMENT", obj.id)
        what = " and ".join(
            f"the {VOICE_EDITABLE[k]} to {'yes' if v is True else 'no' if v is False else v}" for k, v in fields.items())
        label = f"set {what} on {name}"
        item = _item(logic._to_dict(obj, "DEPLOYMENT"))
        return _say(f"Shall I {label}? Say yes or no.", "confirm", results=[item], focus=obj.id,
                    action={"kind": "edit", "recordType": "DEPLOYMENT", "id": obj.id, "fields": fields,
                            "needsReason": False, "label": label, "route": item["route"]})

    if intent == "reassign":
        number = str(plan.get("number") or "")
        if not is_admin(user):
            return _say("Only DevOps admins can assign deployments.", "error")
        found = _find_one(db, user, "DEPLOYMENT", number) if number else []
        if not found:
            return _say(f"I couldn't find deployment {int(number or 0)}.", "error")
        obj = found[0][1]
        who = str(plan.get("who") or "").strip()
        devops = logic.active_devops_users(db)
        if who.lower() in ("me", "myself", "i"):
            match = [d for d in devops if d["id"] == user.id]
        else:
            match = [d for d in devops if _name_match(who, d["name"])]
            if len(match) > 1:
                exact = [d for d in match if _squash(who) in (_squash(d["name"]), _squash(d["name"].split(" ")[0]))]
                match = exact or match
        if len(match) != 1:
            people = ", ".join(d["name"].split(" ")[0] for d in devops[:8])
            return _say((f"Which DevOps engineer? I have: {people}." if match or who else "Assign it to whom?")
                        if devops else "There are no active DevOps users.", "clarify",
                        carry=f"assign deployment {_num(obj.id)} to")
        person = match[0]
        name = _short("DEPLOYMENT", obj.id)
        label = f"assign {name} to {person['name']}"
        item = _item(logic._to_dict(obj, "DEPLOYMENT"))
        return _say(f"Shall I {label}? Say yes or no.", "confirm", results=[item], focus=obj.id,
                    action={"kind": "reassign", "recordType": "DEPLOYMENT", "id": obj.id, "newDevOpsId": person["id"],
                            "needsReason": False, "label": label, "route": item["route"]})

    if intent == "status_change":
        kind, number, new_status = plan.get("kind") or "DEPLOYMENT", str(plan.get("number") or ""), plan.get("new_status")
        if kind == "AWS_ISSUE":
            found = _find_one(db, user, "AWS_ISSUE", number) if number else []
            if found:
                item = _item(logic._to_dict(found[0][1], "AWS_ISSUE"))
                return _say("AWS issues need a root cause and resolution, so please update it on the page. Opening it now.",
                            "open", route=item["route"], results=[item])
            return _say("I can't change AWS issues by voice.", "error")
        if user.role != "DevOps":
            return _say("Only DevOps users can change the status.", "error")
        found = _find_one(db, user, kind, number) if number else []
        if not found:
            return _say(f"I couldn't find {KIND_LABEL[kind]} {int(number or 0)}.", "error")
        obj = found[0][1]
        transitions = logic.DEPLOYMENT_TRANSITIONS if kind == "DEPLOYMENT" else logic.ACCESS_TRANSITIONS
        if new_status not in transitions.get(obj.status, []) and not is_admin(user):
            return _say(f"{_short(kind, obj.id).capitalize()} is {logic._label(obj.status).lower()}, "
                        f"so it can't be marked {logic._label(new_status).lower()}.", "error")
        verb = {"APPROVED": "approve", "REJECTED": "reject", "IN_PROGRESS": "start", "COMPLETED_SUCCESS": "mark as deployed successfully",
                "COMPLETED_FAILED": "mark as failed", "ROLLED_BACK": "roll back", "ACCESS_GIVEN": "mark as given"}[new_status]
        label = f"{verb} {_short(kind, obj.id)}" if not verb.startswith("mark") else f"{verb.split(' ', 1)[0]} {_short(kind, obj.id)} {verb.split(' ', 1)[1]}"
        item = _item(logic._to_dict(obj, kind))
        return _say(f"Shall I {label}? Say yes or no.", "confirm", results=[item],
                    action={"kind": "status_change", "recordType": kind, "id": obj.id, "newStatus": new_status,
                            "needsReason": new_status in NEEDS_REASON, "label": label, "route": item["route"]})

    if intent in ("list", "count"):
        kind = plan.get("kind") or "DEPLOYMENT"
        f = {k: plan.get(k) for k in ("status", "env", "project", "date", "mine", "by", "by_name")}
        rows = _fetch(db, ctx, user, kind, f)
        n, phrase = len(rows), _phrase(kind, f)
        items = [_item(logic._to_dict(r, kind)) for r in rows[:8]]
        if intent == "count":
            return _say(f"There {'is' if n == 1 else 'are'} {n} {phrase}.", "count", results=items)
        plain = not (f["env"] or f["project"] or f["date"] or f["mine"] or f["by"])
        route = (KIND_ROUTE[kind] + (f"?status={f['status']}" if f["status"] else "")) if plain else None
        if n == 0:
            return _say(f"There are no {phrase}.", "list", results=[], route=route)
        speech = f"I found {n} {phrase}."
        if n > 1:
            speech += " Here are the latest."
        return _say(speech, "list", results=items, route=route)

    if intent == "summary":
        parts = []
        for kind in KINDS:
            if not logic.can_view_record(user, kind):
                continue
            model = logic._MODEL_BY_TYPE[kind]
            cq = db.query(model.status, func.count())
            if hasattr(model, "deleted"):
                cq = cq.filter(model.deleted.is_(False))
            if not logic.sees_all_records(user):
                cq = cq.filter(model.requester_id == user.id)
            counts = Counter({st: c for st, c in cq.group_by(model.status).all()})
            if counts:
                parts.append(f"{sum(counts.values())} {KIND_PLURAL[kind]}: " +
                             ", ".join(f"{c} {STATUS_SPOKEN.get(s, str(s).lower())}" for s, c in counts.most_common(4)))
        return _say(("Here is the summary. " + ". ".join(parts) + ".") if parts else "There are no records yet.", "summary")

    if intent == "search" or intent == "unknown":
        term = plan.get("term") or " ".join(w for w in t.split() if w not in _STOPWORDS)
        term = term.strip()
        if len(term) < 2:
            return _say("Sorry, I didn't understand that. Say help to hear what I can do.", "unknown", examples=EXAMPLES)
        rows = logic.handle_search(db, term, ctx)
        if not rows:
            return _say(f"Sorry, I couldn't find anything for {term}. Say help to hear what I can do.", "unknown", examples=EXAMPLES)
        items = [_item(r) for r in rows[:8]]
        if len(rows) == 1:
            return _say(f"I found one match: {_short(items[0]['type'], items[0]['id'])}. Opening it.", "open",
                        route=items[0]["route"], results=items)
        return _say(f"I found {len(rows)} results for {term}.", "search", results=items)

    return _say("Sorry, I didn't understand that.", "unknown", examples=EXAMPLES)


# ---------------------------------------------------------------------
# Entry point (called from main.py)
# ---------------------------------------------------------------------

_apps_cache: dict = {"at": 0.0, "apps": []}


def _apps(db: Session) -> list[str]:
    """Application names, cached for a few seconds (asked on every voice command)."""
    if time.monotonic() - _apps_cache["at"] > 15 or not _apps_cache["apps"]:
        _apps_cache["apps"] = logic.handle_get_config(db)["applications"]
        _apps_cache["at"] = time.monotonic()
    return _apps_cache["apps"]


def _focus_ref(context: dict) -> str | None:
    """The record "it" / "this one" means: the one on screen, else the last one talked about,
    else the only result shown."""
    context = context if isinstance(context, dict) else {}
    for key in ("recordId", "lastRecordId"):
        if split_ref(context.get(key))[0]:
            return str(context[key]).upper()
    results = [r for r in (context.get("results") or []) if split_ref(r)[0]]
    return str(results[0]).upper() if len(results) == 1 else None


_KNOWN = set("""deployment deployments deploy deploys dep release releases access accesses acc request requests
requested permission permissions issue issues aws incident incidents outage outages fail failed failing failure
failures broken error errors success successful successfully succeeded completed deployed done live progress
ongoing running started approved rejected declined denied granted given resolved closed fixed pending waiting new
unapproved unresolved dev development qa uat prod production today tomorrow yesterday week month last this how many
count number total my mine i raised created which what where when who whose is are were was have has latest recent
top first next one ones us our we you status rolled roll back rollback out so far right now currently current
just only also than more less them those these it its were env environment app application applications project
projects list display show shown give tell went gone got did had does doing yet still please need want see""".split())


def _unexplained(t: str, apps: list[str]) -> list[str]:
    """Words the rule parser did not use (a name, an unusual condition...)."""
    app_words = {w for a in apps for w in re.split(r"[^a-z0-9]+", a.lower()) if w}
    return [w for w in t.split() if len(w) > 2 and not w.isdigit() and w not in _STOPWORDS
            and w not in _KNOWN and w not in app_words]


def _wants_agent(plan: dict, t: str, apps: list[str] | None = None) -> bool:
    intent = plan.get("intent")
    words = len(t.split())
    if intent in ("list", "count") and _unexplained(t, apps or []):
        return True        # "what has keshava been pushing to prod" - rules would ignore 'keshava'

    if intent == "unknown":
        return True
    if intent == "clarify" and plan.get("verb") != "create":
        return True        # "approve the stylo one" - the agent can look it up
    if intent in ("list", "count", "search") and words >= 9:
        return True        # long, conversational sentences: rules may miss a detail
    if intent == "ask" and plan.get("field") is None and words >= 7:
        return True
    return False


def handle_voice_command(db: Session, body: dict, ctx: Ctx) -> dict:
    started = time.perf_counter()
    user = require_auth(ctx)
    raw = str(body.get("text") or "").strip()[:500]
    if not raw:
        return _say("I didn't catch that. Please try again.", "empty")
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    ref = _focus_ref(context)
    apps = _apps(db)
    t = normalize(raw)

    plan, source = _special(raw, t, ref), "rules"
    if plan is None:
        plan = parse(t, apps, ref)
    if _wants_agent(plan, t, apps) and llm.enabled():
        ai = agent_plan(db, ctx, user, raw, apps, body.get("history"), ref, str(context.get("route") or ""))
        if ai:
            plan, source = ai, "ai"
    try:
        out = _execute(db, ctx, user, plan, t)
    except ApiError as e:
        out = _say(str(e), "error")
    if "focus" not in out and isinstance(out.get("results"), list) and len(out["results"]) == 1:
        out["focus"] = out["results"][0]["id"]
    out["source"] = source
    out["heard"] = raw
    out["ms"] = int((time.perf_counter() - started) * 1000)
    return out