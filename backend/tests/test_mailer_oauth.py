# Run from the backend folder:  python tests/test_mailer_oauth.py
# smtp_oauth = SMTP on smtp.office365.com with an OAuth2 (XOAUTH2) token, like the Node/nodemailer app.
import base64, os, sys
os.environ["DATABASE_URL"] = "sqlite://"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app import mailer
from app.config import settings
from app.mailer import OutgoingEmail, MailError

settings.MAIL_ENABLED = True
settings.MAIL_PROVIDER = "smtp_oauth"
settings.MAIL_FROM_ADDRESS = "no-reply@axiotechx.com"
settings.SMTP_USERNAME = ""
settings.GRAPH_TENANT_ID = settings.GRAPH_CLIENT_ID = settings.GRAPH_CLIENT_SECRET = "x"
mailer._smtp_oauth_access_token = lambda: "TOKEN123"

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  PASS", label)
    else: fail += 1; print("  FAIL", label, extra)

class Fake:
    code = 235
    def __init__(self, *a, **k): self.cmds = []; self.sent = []; Fake.last = self
    def ehlo(self): pass
    def starttls(self, context=None): pass
    def docmd(self, cmd, args=""): self.cmds.append((cmd, args)); return (Fake.code, b"reply")
    def send_message(self, msg, to_addrs=None): self.sent.append(list(to_addrs)); return {}
    def quit(self): pass
    def close(self): pass
mailer.smtplib.SMTP = Fake

mail = OutgoingEmail(subject="[OPSFlow] t", html="<p>x</p>", text="x", to=[("", "hari@axiotechx.com")])
r = mailer.send_now(mail)
cmd, arg = Fake.last.cmds[0]
blob = base64.b64decode(arg.split()[1]).decode()
check("AUTH XOAUTH2 carries mailbox + bearer token", cmd == "AUTH" and arg.startswith("XOAUTH2 ")
      and blob == "user=no-reply@axiotechx.com\x01auth=Bearer TOKEN123\x01\x01", blob)
check("message delivered over the OAuth session", r["sent"] == ["hari@axiotechx.com"], r)
Fake.code = 535
try:
    mailer.send_now(mail); check("refused login raises", False)
except MailError as e:
    check("refused login -> permanent, mentions Authenticated SMTP", e.permanent and "Authenticated SMTP" in str(e), str(e))
print(f"\n{ok} passed, {fail} failed"); sys.exit(1 if fail else 0)
