"""
Professional, Outlook-safe HTML + plain-text e-mail layouts.

Outlook desktop renders HTML with the Word engine, so this uses nested
tables and inline styles only (no flexbox, no external CSS). Every value
that comes from a user is HTML-escaped. One `Mail` description renders both
the HTML and the plain-text alternative.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .config import settings

FONT = "Segoe UI, Calibri, Arial, sans-serif"
_URL = re.compile(r"^https?://\S+$", re.I)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def fmt_dt(value) -> str:
    """'28 Sep 2026, 03:30 PM IST' in MAIL_TIMEZONE."""
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        local = value.astimezone(ZoneInfo(settings.MAIL_TIMEZONE))
        label = local.tzname() or settings.MAIL_TIMEZONE
    except Exception:  # tzdata missing -> fall back to IST offset / UTC
        if settings.MAIL_TIMEZONE == "Asia/Kolkata":
            local, label = value.astimezone(timezone(timedelta(hours=5, minutes=30))), "IST"
        else:
            local, label = value.astimezone(timezone.utc), "UTC"
    return f"{local.day} {local:%b %Y}, {local:%I:%M %p} {label}"


def _esc(text) -> str:
    return html.escape(str(text if text not in (None, "") else "—"), quote=True).replace("\n", "<br>")


def _value_html(text) -> str:
    raw = str(text or "").strip()
    if _URL.match(raw):
        safe = html.escape(raw, quote=True)
        return f'<a href="{safe}" style="color:#1d4ed8;text-decoration:none;">{safe}</a>'
    return _esc(raw)


# ---------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------

@dataclass
class Section:
    heading: str
    rows: list[tuple[str, str]] = field(default_factory=list)      # label / value pairs
    blocks: list[tuple[str, str]] = field(default_factory=list)    # label / long text


@dataclass
class Mail:
    eyebrow: str                       # small text above the title
    title: str
    accent: str                        # header colour, e.g. "#1e3a8a"
    greeting: str
    intro: str
    sections: list[Section]
    accent_text: str = ""              # contrasting text / button colour for light accents
    cta_label: str = ""
    cta_url: str = ""
    chips: list[tuple[str, str]] = field(default_factory=list)     # (text, colour)
    warning: str = ""                  # yellow call-out box
    sign_name: str = ""                # "Regards, <name>"
    sign_role: str = ""
    sign_email: str = ""
    preheader: str = ""


# ---------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------

def render_html(m: Mail) -> str:
    accent_text = m.accent_text or "#ffffff"
    chips = "".join(
        f'<span style="display:inline-block;background:{c};color:#ffffff;font-size:11px;font-weight:600;'
        f'padding:3px 10px;border-radius:10px;margin-right:6px;letter-spacing:.3px;">{_esc(t)}</span>'
        for t, c in m.chips
    )

    sections = []
    for s in m.sections:
        rows = "".join(
            f'<tr><td width="170" valign="top" style="padding:7px 12px;background:#f9fafb;border-bottom:1px solid #eef0f3;'
            f'font-size:13px;color:#6b7280;">{_esc(k)}</td>'
            f'<td valign="top" style="padding:7px 12px;border-bottom:1px solid #eef0f3;font-size:13px;color:#111827;">'
            f'{_value_html(v)}</td></tr>'
            for k, v in s.rows
        )
        blocks = "".join(
            f'<tr><td colspan="2" style="padding:10px 12px;border-bottom:1px solid #eef0f3;">'
            f'<div style="font-size:12px;color:#6b7280;margin-bottom:4px;">{_esc(k)}</div>'
            f'<div style="font-size:13px;color:#111827;line-height:1.5;">{_value_html(v)}</div></td></tr>'
            for k, v in s.blocks
        )
        sections.append(
            f'<tr><td style="padding:18px 28px 0 28px;">'
            f'<div style="font-size:12px;font-weight:700;color:{m.accent_text or m.accent};letter-spacing:.8px;text-transform:uppercase;'
            f'padding-bottom:6px;">{_esc(s.heading)}</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border:1px solid #e5e7eb;border-collapse:collapse;">{rows}{blocks}</table></td></tr>'
        )

    warning = (
        f'<tr><td style="padding:18px 28px 0 28px;"><div style="background:#fffbeb;border:1px solid #fcd34d;'
        f'border-left:4px solid #f59e0b;padding:10px 14px;font-size:13px;color:#92400e;">'
        f'<b>Attention:</b> {_esc(m.warning)}</div></td></tr>' if m.warning else ""
    )
    cta = (
        f'<tr><td style="padding:24px 28px 0 28px;"><table role="presentation" cellpadding="0" cellspacing="0"><tr>'
        f'<td bgcolor="{m.accent_text or m.accent}" style="border-radius:6px;"><a href="{html.escape(m.cta_url, quote=True)}" '
        f'style="display:inline-block;padding:11px 24px;font-size:14px;font-weight:600;color:#ffffff;'
        f'text-decoration:none;font-family:{FONT};">{_esc(m.cta_label)}</a></td></tr></table></td></tr>'
        if m.cta_url else ""
    )
    signature = ""
    if m.sign_name:
        role = f'<div style="color:#6b7280;">{_esc(m.sign_role)}</div>' if m.sign_role else ""
        mail = (f'<div><a href="mailto:{html.escape(m.sign_email, quote=True)}" style="color:#1d4ed8;text-decoration:none;">'
                f'{_esc(m.sign_email)}</a></div>' if m.sign_email else "")
        signature = (
            f'<tr><td style="padding:26px 28px 0 28px;font-size:14px;color:#111827;line-height:1.5;">'
            f'Regards,<br><b>{_esc(m.sign_name)}</b>{role}{mail}</td></tr>'
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(m.title)}</title></head>
<body style="margin:0;padding:0;background:#f3f4f6;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#f3f4f6;">{_esc(m.preheader or m.intro)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0"
 style="width:640px;max-width:100%;background:#ffffff;border:1px solid #e5e7eb;font-family:{FONT};color:#111827;">
<tr><td bgcolor="{m.accent}" style="padding:22px 28px;background:{m.accent};">
  <div style="font-size:11px;letter-spacing:1.4px;color:{accent_text};text-transform:uppercase;font-weight:600;">{_esc(m.eyebrow)}</div>
  <div style="font-size:21px;font-weight:700;color:{accent_text};margin:6px 0 10px 0;line-height:1.3;">{_esc(m.title)}</div>
  <div>{chips}</div>
</td></tr>
<tr><td style="padding:24px 28px 0 28px;font-size:14px;line-height:1.6;color:#111827;">
  <div style="margin-bottom:10px;">{_esc(m.greeting)}</div>
  <div>{_esc(m.intro)}</div>
</td></tr>
{warning}
{''.join(sections)}
{cta}
{signature}
<tr><td style="padding:28px 28px 22px 28px;">
  <div style="border-top:1px solid #e5e7eb;padding-top:12px;font-size:11px;color:#9ca3af;line-height:1.5;">
  This is an automated message from OPSFlow. Replies go to the person who raised this request.
  You can turn e-mail notifications off any time from Profile &rarr; Preferences in OPSFlow.
  </div>
</td></tr>
</table></td></tr></table></body></html>"""


def render_text(m: Mail) -> str:
    out = [m.greeting, "", m.intro, ""]
    if m.warning:
        out += [f"ATTENTION: {m.warning}", ""]
    for s in m.sections:
        out += [s.heading.upper(), "-" * len(s.heading)]
        out += [f"{k}: {v or '—'}" for k, v in s.rows]
        for k, v in s.blocks:
            out += [f"{k}:", f"  {v or '—'}"]
        out.append("")
    if m.cta_url:
        out += [f"{m.cta_label}: {m.cta_url}", ""]
    if m.sign_name:
        out += ["Regards,", m.sign_name]
        if m.sign_role:
            out.append(m.sign_role)
        if m.sign_email:
            out.append(m.sign_email)
        out.append("")
    out += ["--", "Automated message from OPSFlow. Manage e-mail notifications under Profile > Preferences."]
    return "\n".join(out)
