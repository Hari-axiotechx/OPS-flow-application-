"""
Outbound e-mail transport for OPSFlow (Microsoft Graph (recommended), Microsoft 365 SMTP or AWS SES SMTP).

Providers, chosen with MAIL_PROVIDER:

  smtp   Authenticated SMTP submission.  Port 587 = STARTTLS (default), port 465 =
         implicit TLS.  Works with AWS SES (email-smtp.<region>.amazonaws.com) and
         smtp.office365.com.
  smtp_oauth  SMTP on smtp.office365.com with an OAuth2 token (XOAUTH2) from the Entra ID app
         registration (tenant id + client id + client secret). This is what the Node/nodemailer
         app does (scope https://outlook.office365.com/.default). No password and no Graph
         Mail.Send permission needed.
  graph  Microsoft Graph "sendMail" with an app registration (client credentials).

Design rules
  * E-mails are QUEUED on the DB session while a request is being handled and
    only sent AFTER the transaction commits (see dispatch_pending, called by
    main.py). A rolled-back request never sends an e-mail.
  * Sending happens on a small background thread pool, so a slow mail server
    never slows down or fails an API request.
  * A failed send is RETRIED (MAIL_RETRIES times, with back-off).
  * If the server rejects the message because of ONE bad recipient (typical with
    AWS SES in sandbox mode: "Email address is not verified"), the message is
    re-sent to every recipient separately, so one unverified address can never
    stop the others from getting their e-mail.
  * A failure is never silent: it is logged with the real server reply AND the
    person who raised the request gets an in-app notification saying the e-mail
    was not delivered and why.
  * MAIL_ENABLED=false  ->  dry-run: nothing is sent, the e-mail is printed to the
    log and the requester is told in-app that mail is switched off.

Check your setup any time:
    docker compose exec backend python -m app.mailer you@axiotechx.com
(or, as an admin, use "Send test email" on the Profile page).
"""
from __future__ import annotations

import base64
import json
import logging
import re
import smtplib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .config import settings

log = logging.getLogger("opsflow.mail")
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="opsflow-mail")

Address = tuple[str, str]  # (display name, e-mail address)


@dataclass
class OutgoingEmail:
    subject: str
    html: str
    text: str
    to: list[Address]
    cc: list[Address] = field(default_factory=list)
    reply_to: Address | None = None
    from_name: str = ""          # e.g. "Madhan via OPSFlow"
    record_id: str = ""          # e.g. DEP-000012 (used in the failure notification)
    actor_id: str = ""           # who raised it (told in-app when delivery fails)
    send_inline: bool = False    # critical account mail must finish before a Lambda response returns


class MailError(RuntimeError):
    """A send failed. `permanent` = retrying the same message will not help."""

    def __init__(self, message: str, permanent: bool = False, rejected: dict | None = None):
        super().__init__(message)
        self.permanent = permanent
        self.rejected = rejected or {}


def _clean(value: str) -> str:
    """Strip CR/LF/tabs so user-supplied names can never inject headers."""
    return re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()


def _addr(a: Address) -> Address:
    return (_clean(a[0]), _clean(a[1]))


# ---------------------------------------------------------------------
# Queue: send only after the DB transaction commits
# ---------------------------------------------------------------------

def queue_email(db, message: OutgoingEmail) -> None:
    db.info.setdefault("pending_emails", []).append(message)


def discard_pending(db) -> None:
    db.info.pop("pending_emails", None)


def dispatch_pending(db) -> None:
    for message in db.info.pop("pending_emails", []):
        if message.send_inline:
            _deliver(message)
            continue
        try:
            _pool.submit(_deliver, message)
        except Exception:  # e.g. pool shut down: the request itself must still succeed
            log.exception("Could not hand e-mail to the sender: %s", message.subject)


# ---------------------------------------------------------------------
# Delivery with retry + failure reporting
# ---------------------------------------------------------------------

def _deliver(m: OutgoingEmail) -> None:
    try:
        if not settings.MAIL_ENABLED:
            log.warning(
                "[dry-run] MAIL_ENABLED=false, e-mail NOT sent.\n  Subject: %s\n  To: %s\n  Cc: %s",
                m.subject, ", ".join(e for _, e in m.to), ", ".join(e for _, e in m.cc) or "-",
            )
            _tell_actor(m, "E-mail not sent",
                        f"E-mail is switched off on the server (MAIL_ENABLED=false), so no e-mail went out for {m.record_id or 'your request'}. "
                        "Ask your administrator to set MAIL_ENABLED=true.")
            return

        attempts = max(1, int(settings.MAIL_RETRIES))
        delay = max(0.0, float(settings.MAIL_RETRY_DELAY_SECONDS))
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                result = send_now(m)
                failed = (result or {}).get("failed") or {}
                if failed:
                    names = ", ".join(f"{a} ({why})" for a, why in failed.items())
                    log.warning("E-mail partly delivered: %s. Not delivered to: %s", m.subject, names)
                    _tell_actor(m, "E-mail not delivered to some people",
                                f"{m.record_id or 'Your request'}: the e-mail could not be delivered to {names}.")
                log.info("E-mail sent (attempt %d): %s -> %s", attempt, m.subject, ", ".join(e for _, e in m.to))
                return
            except MailError as e:
                last = e
                if e.permanent:
                    break
            except Exception as e:  # network error, timeout, etc.
                last = e
            if attempt < attempts:
                log.warning("E-mail attempt %d/%d failed (%s). Retrying in %.0fs: %s",
                            attempt, attempts, last, delay * (2 ** (attempt - 1)), m.subject)
                time.sleep(delay * (2 ** (attempt - 1)))

        log.error("E-mail FAILED after %d attempt(s): %s | %s", attempts, m.subject, last)
        _tell_actor(m, "E-mail could not be sent",
                    f"{m.record_id or 'Your request'} was saved, but its e-mail could not be sent: {_short(last)}")
    except Exception:  # never let a mail problem surface to the user
        log.exception("E-mail FAILED: %s", m.subject)


def _short(err: Exception | None, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(err or "unknown error")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _record_link(record_id: str) -> str:
    base = {"DEP": "/deployments/", "ACC": "/access/", "AWS": "/aws-issues/"}.get((record_id or "")[:3])
    return f"{base}{record_id}" if base else ""


def _tell_actor(m: OutgoingEmail, title: str, message: str) -> None:
    """In-app notification for the person who raised the request."""
    if not m.actor_id:
        return
    try:
        from .database import SessionLocal
        from .models import Notification
        from .ids import generate_id
        from .logic import now
        db = SessionLocal()
        try:
            db.add(Notification(
                id=generate_id(db, "NOTIFICATION"), recipient_id=m.actor_id, kind="email",
                title=title, message=message, link=_record_link(m.record_id), record_id=m.record_id or None,
                actor="System", read=False, created_at=now(),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        log.exception("Could not store the e-mail failure notification")


def send_now(m: OutgoingEmail) -> dict:
    """Synchronous send. Raises MailError / OSError on failure.
    Returns {"sent": [addresses], "failed": {address: reason}}."""
    if not settings.MAIL_FROM_ADDRESS:
        raise MailError("MAIL_FROM_ADDRESS is not set.", permanent=True)
    if not m.to:
        raise MailError("No recipients.", permanent=True)
    provider = (settings.MAIL_PROVIDER or "graph").strip().lower()
    if provider == "graph":
        try:
            _send_graph(m)
            return {"sent": [e for _, e in m.to + m.cc], "failed": {}}
        except Exception as graph_error:
            if not (settings.MAIL_FALLBACK_SMTP and settings.smtp_ready):
                raise
            log.warning("Microsoft Graph failed (%s). Trying SMTP instead.", _short(graph_error))
            try:
                return _send_smtp(m)
            except Exception as smtp_error:
                raise MailError(f"Graph: {_short(graph_error, 300)} | SMTP: {_short(smtp_error, 300)}",
                                permanent=isinstance(graph_error, MailError) and graph_error.permanent
                                and isinstance(smtp_error, MailError) and smtp_error.permanent) from smtp_error
    if provider in ("smtp", "smtp_oauth"):
        return _send_smtp(m)
    raise MailError(f"Unknown MAIL_PROVIDER '{settings.MAIL_PROVIDER}' (use smtp, smtp_oauth or graph).", permanent=True)


def _from_header(m: OutgoingEmail) -> str:
    return formataddr((_clean(m.from_name) or settings.MAIL_FROM_NAME, settings.MAIL_FROM_ADDRESS.strip()))


# ---------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------

def _smtp_connect() -> smtplib.SMTP:
    if (settings.MAIL_PROVIDER or "").strip().lower() == "smtp_oauth":
        return _smtp_connect_oauth()
    host = (settings.SMTP_HOST or "").strip()
    port = int(settings.SMTP_PORT)
    user = (settings.SMTP_USERNAME or settings.MAIL_FROM_ADDRESS).strip()
    password = (settings.SMTP_PASSWORD or "").strip()
    if not host:
        raise MailError("SMTP_HOST is not set.", permanent=True)
    if not password:
        raise MailError("SMTP_PASSWORD is not set.", permanent=True)
    ctx = ssl.create_default_context()
    secure = str(settings.SMTP_SECURE).strip().lower() in ("true", "1", "yes")
    if port == 465 or secure:                        # implicit TLS
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx)
        smtp.ehlo()
    else:                                            # 587 / 2587 / 25: STARTTLS
        smtp = smtplib.SMTP(host, port, timeout=30)
        smtp.ehlo()
        smtp.starttls(context=ctx)
        smtp.ehlo()
    try:
        smtp.login(user, password)
    except smtplib.SMTPAuthenticationError as e:
        smtp.close()
        raise MailError(
            f"SMTP login refused by {host} ({e.smtp_code}). Check SMTP_USERNAME / SMTP_PASSWORD "
            "(for AWS SES use the *SMTP* credentials, not the console password).", permanent=True) from e
    return smtp


_smtp_oauth_token: dict = {"value": None, "expires": 0.0}
OUTLOOK_SCOPE = "https://outlook.office365.com/.default"


def _smtp_oauth_access_token() -> str:
    """App-only token for Exchange Online SMTP (same as the nodemailer app's MSAL call)."""
    if _smtp_oauth_token["value"] and time.time() < _smtp_oauth_token["expires"] - 60:
        return _smtp_oauth_token["value"]
    tenant, cid, secret = (settings.GRAPH_TENANT_ID or "").strip(), (settings.GRAPH_CLIENT_ID or "").strip(), (settings.GRAPH_CLIENT_SECRET or "").strip()
    missing = [n for n, v in (("GRAPH_TENANT_ID (or AZURE_TENANT_ID)", tenant), ("GRAPH_CLIENT_ID (or AZURE_CLIENT_ID)", cid),
                              ("GRAPH_CLIENT_SECRET (or AZURE_CLIENT_SECRET)", secret)) if not v]
    if missing:
        raise MailError("MAIL_PROVIDER=smtp_oauth but these are empty in .env: " + ", ".join(missing), permanent=True)
    url = f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({"client_id": cid, "client_secret": secret,
                                   "scope": OUTLOOK_SCOPE, "grant_type": "client_credentials"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise MailError(f"Microsoft sign-in failed ({e.code}): {_graph_error_text(e)}. Check the tenant id, client id and that the "
                        "client secret is the secret VALUE (not the secret ID) and has not expired.",
                        permanent=e.code in (400, 401, 403)) from e
    _smtp_oauth_token["value"] = body["access_token"]
    _smtp_oauth_token["expires"] = time.time() + int(body.get("expires_in", 3600))
    return _smtp_oauth_token["value"]


def _smtp_connect_oauth() -> smtplib.SMTP:
    host = (settings.SMTP_HOST or "smtp.office365.com").strip()
    port = int(settings.SMTP_PORT)
    user = (settings.SMTP_USERNAME or settings.MAIL_FROM_ADDRESS).strip()
    token = _smtp_oauth_access_token()
    ctx = ssl.create_default_context()
    secure = str(settings.SMTP_SECURE).strip().lower() in ("true", "1", "yes")
    if port == 465 or secure:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx)
        smtp.ehlo()
    else:
        smtp = smtplib.SMTP(host, port, timeout=30)
        smtp.ehlo()
        smtp.starttls(context=ctx)
        smtp.ehlo()
    blob = base64.b64encode(f"user={user}\x01auth=Bearer {token}\x01\x01".encode()).decode()
    code, reply = smtp.docmd("AUTH", "XOAUTH2 " + blob)
    if code == 334:                      # server sent a JSON error challenge; finish the exchange
        code, reply = smtp.docmd("")
    if code != 235:
        smtp.close()
        _smtp_oauth_token["value"] = None
        text = reply.decode(errors="replace") if isinstance(reply, bytes) else str(reply)
        raise MailError(
            f"SMTP OAuth login refused by {host} ({code}): {_short(text, 200)}. Check that (1) 'Authenticated SMTP' is enabled on {user}, "
            "(2) the app's service principal is registered in Exchange Online and has FullAccess on that mailbox "
            "(the Node app needs the same), and (3) SMTP_USERNAME / MAIL_FROM_ADDRESS is that mailbox.", permanent=True)
    return smtp


def _build_message(m: OutgoingEmail, to: list[Address], cc: list[Address]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = _clean(m.subject)
    msg["From"] = _from_header(m)
    msg["To"] = ", ".join(formataddr(a) for a in to)
    if cc:
        msg["Cc"] = ", ".join(formataddr(a) for a in cc)
    if m.reply_to:
        msg["Reply-To"] = formataddr(_addr(m.reply_to))
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=settings.MAIL_FROM_ADDRESS.split("@")[-1].strip() or None)
    msg.set_content(m.text)
    msg.add_alternative(m.html, subtype="html")
    return msg


def _send_smtp(m: OutgoingEmail) -> dict:
    to, cc = [_addr(a) for a in m.to], [_addr(a) for a in m.cc]
    msg = _build_message(m, to, cc)
    everyone = list(dict.fromkeys(e for _, e in to + cc))
    smtp = _smtp_connect()
    try:
        try:
            refused = smtp.send_message(msg, to_addrs=everyone)   # {} when every recipient accepted
            return {"sent": [a for a in everyone if a not in refused],
                    "failed": {a: f"{c} {_short(r if isinstance(r, str) else r.decode(errors='replace'), 120)}"
                               for a, (c, r) in refused.items()}}
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError, smtplib.SMTPSenderRefused) as first:
            # One bad address (e.g. unverified in the SES sandbox) rejects the WHOLE message.
            # Try each recipient on its own so the good ones still get their e-mail.
            if isinstance(first, smtplib.SMTPSenderRefused):
                raise MailError(f"Sender {settings.MAIL_FROM_ADDRESS} was refused by the mail server: "
                                f"{_short(first.smtp_error.decode(errors='replace') if isinstance(first.smtp_error, bytes) else first.smtp_error)}. "
                                "Verify this address/domain in AWS SES.", permanent=True) from first
            log.warning("Mail server rejected the message (%s). Sending to each recipient separately.", _short(first))
            sent, failed = [], {}
            for address in everyone:
                try:
                    smtp.rset()
                except smtplib.SMTPException:
                    smtp.close()
                    smtp = _smtp_connect()
                try:
                    smtp.send_message(msg, to_addrs=[address])
                    sent.append(address)
                except smtplib.SMTPException as e:
                    failed[address] = _short(getattr(e, "smtp_error", None) or str(e), 120)
            if not sent:
                raise MailError("The mail server rejected every recipient: " +
                                "; ".join(f"{a}: {w}" for a, w in failed.items()) +
                                ". With AWS SES in sandbox mode, every recipient must be a verified identity "
                                "(or request production access).", permanent=True, rejected=failed) from first
            return {"sent": sent, "failed": failed}
    finally:
        try:
            smtp.quit()
        except Exception:
            smtp.close()


def _smtp_check_text() -> str:
    smtp = _smtp_connect()
    smtp.quit()
    how = "with OAuth2 (client credentials)" if (settings.MAIL_PROVIDER or "").lower() == "smtp_oauth" else "with a password"
    return f"OK: logged in {how} to {settings.SMTP_HOST}:{settings.SMTP_PORT} as {settings.SMTP_USERNAME or settings.MAIL_FROM_ADDRESS}."


def check_smtp() -> str:
    """Connect + log in without sending anything. Returns a human-readable verdict."""
    if not settings.MAIL_ENABLED:
        return "MAIL_ENABLED=false (dry-run): no e-mail will leave the server."
    provider = (settings.MAIL_PROVIDER or "graph").lower()
    if provider == "graph":
        _graph_access_token()
        roles = _graph_roles()
        if "Mail.Send" not in roles and settings.MAIL_FALLBACK_SMTP and settings.smtp_ready:
            return (f"Graph has no Mail.Send permission yet (permissions in token: {', '.join(roles) or 'none'}), "
                    f"but SMTP backup is ready: {_smtp_check_text()}")
        if "Mail.Send" not in roles:
            raise MailError("Signed in to Microsoft, but the app has NO Mail.Send application permission "
                            f"(permissions in token: {', '.join(roles) or 'none'}). Add Mail.Send (Application) and grant admin consent.",
                            permanent=True)
        return f"OK: signed in to Microsoft Graph with Mail.Send; mails are sent as {settings.MAIL_FROM_ADDRESS}."
    if provider not in ("smtp", "smtp_oauth"):
        raise MailError(f"Unknown MAIL_PROVIDER '{settings.MAIL_PROVIDER}' (use smtp, smtp_oauth or graph).", permanent=True)
    return _smtp_check_text()


def startup_report() -> None:
    """Printed once when the backend starts, so a broken mail set-up is obvious in `docker compose logs backend`."""
    try:
        if (settings.MAIL_PROVIDER or "").lower() in ("graph", "smtp_oauth"):
            log.warning("E-mail config: enabled=%s provider=" + settings.MAIL_PROVIDER.lower() + " from=%s tenant_set=%s client_id_set=%s secret_set=%s base_url=%s",
                        settings.MAIL_ENABLED, settings.MAIL_FROM_ADDRESS, bool(settings.GRAPH_TENANT_ID.strip()),
                        bool(settings.GRAPH_CLIENT_ID.strip()), bool(settings.GRAPH_CLIENT_SECRET.strip()), settings.APP_BASE_URL)
        else:
            log.warning("E-mail config: enabled=%s provider=%s host=%s:%s from=%s user=%s password_set=%s base_url=%s",
                        settings.MAIL_ENABLED, settings.MAIL_PROVIDER, settings.SMTP_HOST, settings.SMTP_PORT,
                        settings.MAIL_FROM_ADDRESS, "yes" if settings.SMTP_USERNAME else "NO", bool(settings.SMTP_PASSWORD),
                        settings.APP_BASE_URL)
        log.warning("E-mail check: %s", check_smtp())
    except Exception as e:
        log.error("E-mail check FAILED: %s  <-- fix this, otherwise no e-mail can be sent.", _short(e, 400))


# ---------------------------------------------------------------------
# Microsoft Graph
# ---------------------------------------------------------------------

_graph_token: dict = {"value": None, "expires": 0.0}


def _graph_error_text(e: urllib.error.HTTPError) -> str:
    """Pull the readable message out of a Microsoft error reply."""
    raw = e.read().decode(errors="replace")
    try:
        body = json.loads(raw)
        err = body.get("error")
        if isinstance(err, dict):
            return f"{err.get('code', '')}: {err.get('message', '')}".strip(": ")
        return f"{err or ''} {body.get('error_description', '')}".strip()
    except ValueError:
        return raw[:300]


def _graph_access_token() -> str:
    if _graph_token["value"] and time.time() < _graph_token["expires"] - 60:
        return _graph_token["value"]
    tenant, cid, secret = (settings.GRAPH_TENANT_ID or "").strip(), (settings.GRAPH_CLIENT_ID or "").strip(), (settings.GRAPH_CLIENT_SECRET or "").strip()
    missing = [n for n, v in (("GRAPH_TENANT_ID", tenant), ("GRAPH_CLIENT_ID", cid), ("GRAPH_CLIENT_SECRET", secret)) if not v]
    if missing:
        raise MailError("Microsoft Graph is selected (MAIL_PROVIDER=graph) but these are empty in .env: "
                        + ", ".join(missing), permanent=True)
    url = f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "client_id": cid, "client_secret": secret,
        "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise MailError(
            f"Microsoft sign-in failed ({e.code}): {_graph_error_text(e)}. Check GRAPH_TENANT_ID, GRAPH_CLIENT_ID and that "
            "GRAPH_CLIENT_SECRET is the secret VALUE (not the secret ID) and has not expired.",
            permanent=e.code in (400, 401, 403)) from e
    _graph_token["value"] = body["access_token"]
    _graph_token["expires"] = time.time() + int(body.get("expires_in", 3600))
    return _graph_token["value"]


def _graph_roles() -> list[str]:
    """The application permissions Microsoft actually put into our access token (the 'roles' claim)."""
    import base64
    try:
        payload = _graph_access_token().split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return list(json.loads(base64.urlsafe_b64decode(payload)).get("roles") or [])
    except Exception:
        return []


def _graph_recipients(items: list[Address]) -> list[dict]:
    return [{"emailAddress": {"name": _clean(n), "address": _clean(e)}} for n, e in items]


def _send_graph(m: OutgoingEmail) -> None:
    message = {
        "subject": _clean(m.subject),
        "body": {"contentType": "HTML", "content": m.html},
        "toRecipients": _graph_recipients(m.to),
        "ccRecipients": _graph_recipients(m.cc),
    }
    if m.reply_to:
        message["replyTo"] = _graph_recipients([m.reply_to])
    payload = json.dumps({"message": message, "saveToSentItems": True}).encode()
    sender = settings.MAIL_FROM_ADDRESS.strip()
    url = f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail"
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Authorization": f"Bearer {_graph_access_token()}",
        "Content-Type": "application/json",
    })
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        roles: list[str] = []
        if e.code in (401, 403):
            roles = _graph_roles() if e.code == 403 else []
            _graph_token["value"] = None          # never reuse a token from before a permission change
        hints = {
            401: "The access token was refused. Check the client secret.",
            403: ("The token has NO 'Mail.Send' application permission (permissions in token: "
                  + (", ".join(roles) if roles else "none") + "). In Entra ID > your app > API permissions: add "
                  "Microsoft Graph > APPLICATION permissions (not Delegated) > Mail.Send, then click 'Grant admin consent', "
                  "wait 2 minutes and try again.") if "Mail.Send" not in roles else
                 (f"The token DOES have Mail.Send, so an Exchange 'Application Access Policy' is blocking {sender} "
                  "(or that mailbox does not exist). Ask your Exchange admin to run: "
                  f"Get-ApplicationAccessPolicy | fl   and add {sender} to the allowed group, or remove the policy."),
            404: f"The mailbox {sender} was not found. MAIL_FROM_ADDRESS must be a real mailbox (or shared mailbox) in your Microsoft 365 tenant.",
        }
        raise MailError(f"Graph sendMail failed ({e.code}): {_graph_error_text(e)}. {hints.get(e.code, '')}".strip(),
                        permanent=e.code in (400, 403, 404)) from e


# ---------------------------------------------------------------------
# python -m app.mailer someone@axiotechx.com
# ---------------------------------------------------------------------

def send_test(target: str) -> dict:
    return send_now(OutgoingEmail(
        subject="[OPSFlow] Test e-mail",
        html="<p>Your OPSFlow e-mail configuration works.</p>",
        text="Your OPSFlow e-mail configuration works.",
        to=[("", target)],
    ))


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else settings.MAIL_FROM_ADDRESS
    if not target:
        sys.exit("Usage: python -m app.mailer you@axiotechx.com")
    if not settings.MAIL_ENABLED:
        sys.exit("MAIL_ENABLED is false - set MAIL_ENABLED=true in .env and restart.")
    print(f"Provider: {settings.MAIL_PROVIDER} | From: {settings.MAIL_FROM_ADDRESS} | To: {target}")
    try:
        print("Connection check:", check_smtp())
    except Exception as e:
        print("Connection check FAILED:", _short(e, 500))
    try:
        res = send_test(target)
        print(f"SUCCESS: test e-mail sent to {target}. Result: {res}")
    except Exception as e:
        sys.exit(f"FAILED: {_short(e, 800)}")
