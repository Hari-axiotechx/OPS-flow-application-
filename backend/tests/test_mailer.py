# Run from the backend folder:  python tests/test_mailer.py
# Simulates AWS SES (sandbox) behaviour: ONE unverified recipient makes the server reject the whole message.
import os, sys, smtplib
os.environ["DATABASE_URL"] = "sqlite://"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app import mailer
from app.config import settings
from app.mailer import OutgoingEmail, MailError

settings.MAIL_ENABLED = True
settings.MAIL_PROVIDER = "smtp"
settings.MAIL_FALLBACK_SMTP = False
settings.MAIL_FROM_ADDRESS = "no-reply@axiotechx.com"
settings.SMTP_PASSWORD = "x"
settings.MAIL_RETRY_DELAY_SECONDS = 0
mailer.time.sleep = lambda s: None

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  PASS", label)
    else: fail += 1; print("  FAIL", label, extra)

VERIFIED = {"hari@axiotechx.com", "eswar@axiotechx.com"}

class FakeSES:
    """Rejects the whole DATA command if any envelope recipient is unverified (SES sandbox)."""
    delivered = []
    def send_message(self, msg, to_addrs=None):
        bad = [a for a in to_addrs if a not in VERIFIED]
        if bad:
            raise smtplib.SMTPDataError(554, f"Message rejected: Email address is not verified: {bad[0]}".encode())
        FakeSES.delivered.append(list(to_addrs)); return {}
    def rset(self): pass
    def quit(self): pass
    def close(self): pass

_orig_send_now = mailer.send_now
mailer._smtp_connect = lambda: FakeSES()

def mail(to, cc=()):
    return OutgoingEmail(subject="[OPSFlow] t", html="<p>x</p>", text="x", to=[("", a) for a in to],
                         cc=[("", a) for a in cc], record_id="DEP-1", actor_id="USR-3")

print("== SES sandbox ==")
FakeSES.delivered = []
r = mailer.send_now(mail(["hari@axiotechx.com"], ["eswar@axiotechx.com"]))
check("all verified -> delivered in one go", r["failed"] == {} and len(FakeSES.delivered) == 1)

FakeSES.delivered = []
r = mailer.send_now(mail(["hari@axiotechx.com"], ["stranger@axiotechx.com", "eswar@axiotechx.com"]))
check("one unverified Cc does NOT block the others", sorted(r["sent"]) == sorted(VERIFIED), r)
check("the unverified one is reported", list(r["failed"]) == ["stranger@axiotechx.com"], r)

try:
    mailer.send_now(mail(["a@x.com"], ["b@x.com"]))
    check("nobody verified -> clear error", False)
except MailError as e:
    check("nobody verified -> clear error naming SES sandbox", "sandbox" in str(e) and e.permanent, str(e))

print("== retry + failure reporting ==")
told = []
mailer._tell_actor = lambda m, title, msg: told.append((title, msg))

calls = {"n": 0}
def flaky(m):
    calls["n"] += 1
    if calls["n"] < 3: raise OSError("connection reset")
    return {"sent": ["hari@axiotechx.com"], "failed": {}}
mailer.send_now = flaky
mailer._deliver(mail(["hari@axiotechx.com"]))
check("transient network error is retried until it works", calls["n"] == 3 and not told, (calls, told))

calls["n"] = -99
mailer._deliver(mail(["hari@axiotechx.com"]))
check("gives up after MAIL_RETRIES attempts", calls["n"] == -99 + settings.MAIL_RETRIES, calls)
check("requester is told in-app when the mail finally fails", len(told) == 1 and "could not be sent" in told[0][0], told)

told.clear(); calls["n"] = 0
def permanent(m): calls["n"] += 1; raise MailError("auth refused", permanent=True)
mailer.send_now = permanent
mailer._deliver(mail(["hari@axiotechx.com"]))
check("permanent error (bad password) is NOT retried", calls["n"] == 1 and len(told) == 1, calls)

told.clear()
mailer.send_now = lambda m: {"sent": ["hari@axiotechx.com"], "failed": {"x@y.com": "550 not verified"}}
mailer._deliver(mail(["hari@axiotechx.com", "x@y.com"]))
check("partial delivery is reported to the requester", len(told) == 1 and "x@y.com" in told[0][1], told)

told.clear(); settings.MAIL_ENABLED = False
mailer._deliver(mail(["hari@axiotechx.com"]))
check("MAIL_ENABLED=false -> requester is told nothing was sent", len(told) == 1 and "MAIL_ENABLED" in told[0][1], told)

print("== Microsoft Graph ==")
import io, json, urllib.error
mailer.send_now = _orig_send_now
settings.MAIL_ENABLED = True; settings.MAIL_PROVIDER = "graph"; settings.MAIL_FALLBACK_SMTP = False
settings.GRAPH_TENANT_ID = settings.GRAPH_CLIENT_ID = settings.GRAPH_CLIENT_SECRET = ""
try:
    mailer.send_now(mail(["hari@axiotechx.com"])); check("empty Graph settings -> clear error", False)
except MailError as e:
    check("empty Graph settings -> names the missing ones", "GRAPH_TENANT_ID" in str(e) and e.permanent, str(e))

settings.GRAPH_TENANT_ID, settings.GRAPH_CLIENT_ID, settings.GRAPH_CLIENT_SECRET = "t", "c", "s"
class Resp:
    def __init__(self, b=b"{}"): self.b = b
    def read(self): return self.b
    def __enter__(self): return self
    def __exit__(self, *a): return False
def http_error(code, body): return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(json.dumps(body).encode()))
state = {"send": "ok", "sent": []}
def fake_urlopen(req, timeout=0):
    if "oauth2" in req.full_url: return Resp(json.dumps({"access_token": "TOK", "expires_in": 3600}).encode())
    if state["send"] != "ok": raise http_error(*state["send"])
    state["sent"].append(json.loads(req.data)); return Resp(b"")
mailer.urllib.request.urlopen = fake_urlopen
mailer._graph_token["value"] = None
r = mailer.send_now(mail(["hari@axiotechx.com"], ["eswar@axiotechx.com"]))
msg = state["sent"][0]["message"]
check("Graph send works and keeps To/Cc/Reply-To", r["failed"] == {} and msg["toRecipients"][0]["emailAddress"]["address"] == "hari@axiotechx.com"
      and msg["ccRecipients"][0]["emailAddress"]["address"] == "eswar@axiotechx.com")
state["send"] = (403, {"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}})
try: mailer.send_now(mail(["a@axiotechx.com"])); check("403 explained", False)
except MailError as e: check("403 -> tells you to add Mail.Send + admin consent", "Mail.Send" in str(e) and e.permanent, str(e))
import base64
def jwt(roles): 
    b = base64.urlsafe_b64encode(json.dumps({"roles": roles}).encode()).decode().rstrip("=")
    return f"h.{b}.s"
tok = {"v": jwt([])}
def fake_urlopen2(req, timeout=0):
    if "oauth2" in req.full_url: return Resp(json.dumps({"access_token": tok["v"], "expires_in": 3600}).encode())
    return fake_urlopen(req, timeout)
mailer.urllib.request.urlopen = fake_urlopen2; mailer._graph_token["value"] = None
state["send"] = (403, {"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}})
try: mailer.send_now(mail(["a@axiotechx.com"])); check("403 without role", False)
except MailError as e: check("403 + token has NO Mail.Send -> says exactly that", "NO 'Mail.Send'" in str(e) and "APPLICATION" in str(e), str(e))
tok["v"] = jwt(["Mail.Send"]); mailer._graph_token["value"] = None
try: mailer.send_now(mail(["a@axiotechx.com"])); check("403 with role", False)
except MailError as e: check("403 + token HAS Mail.Send -> points at Application Access Policy", "Application Access Policy" in str(e), str(e))
check("stale token is dropped after a 403", mailer._graph_token["value"] is None)
mailer.urllib.request.urlopen = fake_urlopen
state["send"] = (404, {"error": {"code": "ErrorInvalidUser", "message": "The requested user is invalid."}})
try: mailer.send_now(mail(["a@axiotechx.com"])); check("404 explained", False)
except MailError as e: check("404 -> says sender mailbox must exist", "mailbox" in str(e), str(e))
state["send"] = (429, {"error": {"code": "TooManyRequests", "message": "slow down"}})
try: mailer.send_now(mail(["a@axiotechx.com"])); check("429 retryable", False)
except MailError as e: check("429 (throttled) is retried, not permanent", not e.permanent, str(e))

print("== Graph fails -> SMTP backup ==")
settings.MAIL_PROVIDER = "graph"; settings.MAIL_FALLBACK_SMTP = True
settings.SMTP_HOST = "smtp.office365.com"; settings.SMTP_USERNAME = "no-reply@axiotechx.com"; settings.SMTP_PASSWORD = "pw"
state["send"] = (403, {"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}})
mailer.urllib.request.urlopen = fake_urlopen
VERIFIED.update({"a@axiotechx.com"}); FakeSES.delivered = []
r = mailer.send_now(mail(["a@axiotechx.com"]))
check("Graph 403 + SMTP filled in -> mail still goes out via SMTP", r["sent"] == ["a@axiotechx.com"] and len(FakeSES.delivered) == 1, r)
settings.SMTP_PASSWORD = ""
try: mailer.send_now(mail(["a@axiotechx.com"])); check("no SMTP password -> Graph error shown", False)
except MailError as e: check("no SMTP password -> no fallback, original Graph error shown", "Mail.Send" in str(e) or "Access" in str(e), str(e))
settings.SMTP_PASSWORD = "pw"
mailer._smtp_connect = lambda: (_ for _ in ()).throw(MailError("SMTP login refused", permanent=True))
try: mailer.send_now(mail(["a@axiotechx.com"])); check("both fail", False)
except MailError as e: check("both fail -> one message with BOTH reasons", "Graph:" in str(e) and "SMTP:" in str(e), str(e))

print("== Madhan's variable names ==")
from app.config import Settings
t = Settings(SMTP_USER="u@x.com", SMTP_FROM="f@x.com", MAIL_FROM_ADDRESS="", SMTP_USERNAME="")
check("SMTP_USER / SMTP_FROM are understood", t.SMTP_USERNAME == "u@x.com" and t.MAIL_FROM_ADDRESS == "f@x.com")
check("Microsoft Graph is the default with no SMTP fallback",
      Settings.model_fields["MAIL_PROVIDER"].default == "graph"
      and Settings.model_fields["MAIL_FALLBACK_SMTP"].default is False)

print(f"\nRESULT: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
