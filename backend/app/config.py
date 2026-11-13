"""
Central settings, loaded from environment variables (see .env.example).
Docker Compose injects these; when running locally without Docker, copy
.env.example to .env and edit it.
"""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg2://opsflow:opsflow@db:5432/opsflow"

    # Signs session tokens. Change this to a long random string in production.
    TOKEN_SECRET: str = "change-me-before-deploying"
    TOKEN_TTL_HOURS: int = 12
    OTP_TTL_MINUTES: int = 10

    # Comma-separated list of origins allowed to call this API (the
    # frontend's dev server / deployed URL).
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # First-run admin account (see app/seed.py). Change the password after
    # first login.
    ADMIN_EMAIL: str = "hariprasad.mylamuru@axiotechx.com"
    ADMIN_PASSWORD: str = "Hari123!"
    ADMIN_NAME: str = "Hariprasad Mylamuru"

    # Only emails ending in this domain may register a new account.
    # Leave blank to allow any domain.
    ALLOWED_EMAIL_DOMAIN: str = "axiotechx.com"

    # ------------------------------------------------------------------
    # Outbound e-mail (AWS SES SMTP / Microsoft 365 / Outlook) — see app/mailer.py
    # ------------------------------------------------------------------
    # E-mail cannot be disabled by an environment variable or user preference.
    MAIL_ENABLED: bool = True
    MAIL_PROVIDER: str = "graph"           # Microsoft 365 mail is sent through Microsoft Graph
    MAIL_FROM_ADDRESS: str = "no-reply@axiotechx.com"   # every OPSFlow e-mail is sent from this address
    MAIL_FROM_NAME: str = "OPSFlow"
    MAIL_TIMEZONE: str = "Asia/Kolkata"    # used to print dates in e-mails
    APP_BASE_URL: str = "http://localhost:5173"   # used for the "Open in OPSFlow" button

    # Roles copied (CC) on deployment requests and AWS issues.
    MAIL_CC_TEAM_ROLES: str = "Developer,QA"

    # provider = smtp  (smtp.office365.com, STARTTLS)
    SMTP_HOST: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    # Same settings under the names a colleague may send you (nodemailer style):
    #   SMTP_USER = SMTP_USERNAME, SMTP_FROM = MAIL_FROM_ADDRESS (only used if that one is empty),
    #   SMTP_SECURE=false -> STARTTLS (port 587),  SMTP_SECURE=true -> implicit TLS (port 465).
    SMTP_USER: str = ""
    SMTP_FROM: str = ""
    SMTP_SECURE: str = ""
    # Keep Graph failures visible; do not silently switch Microsoft mail to SMTP.
    MAIL_FALLBACK_SMTP: bool = False
    # How many times a failed send is retried (network hiccups, throttling) and
    # the pause before the first retry (doubles each time).
    MAIL_RETRIES: int = 3
    MAIL_RETRY_DELAY_SECONDS: float = 2.0

    # provider = graph (Microsoft Graph, app-only; needs Mail.Send permission)
    GRAPH_TENANT_ID: str = ""
    GRAPH_CLIENT_ID: str = ""
    GRAPH_CLIENT_SECRET: str = ""
    # Same three values under the names the Node/nodemailer app uses (AZURE_*).
    AZURE_TENANT_ID: str = ""
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""

    # ------------------------------------------------------------------
    # Free-form voice-assistant interpretation requires this Claude API key.
    # ------------------------------------------------------------------
    ANTHROPIC_API_KEY: str = ""
    VOICE_LLM_MODEL: str = "claude-haiku-5-5"

    # Professional speech-to-text (Deepgram). Optional: empty = browser recognizer.
    DEEPGRAM_API_KEY: str = ""
    STT_MODEL: str = "nova-3"
    STT_LANGUAGE: str = "en-IN"
    # "cloud" = Deepgram also listens for "Hello Ops" (best for distance / quiet voices, uses audio minutes all day).
    # "browser" = the free browser recognizer listens for "Hello Ops" (default).
    STT_WAKE: str = "browser"

    @model_validator(mode="after")
    def _normalize_settings(self):
        self.MAIL_ENABLED = True
        for graph_name, azure_name in (("GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
                                       ("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
                                       ("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET")):
            if not getattr(self, graph_name) and getattr(self, azure_name):
                setattr(self, graph_name, getattr(self, azure_name).strip())
        if not self.SMTP_USERNAME and self.SMTP_USER:
            self.SMTP_USERNAME = self.SMTP_USER.strip()
        if not self.MAIL_FROM_ADDRESS and self.SMTP_FROM:
            self.MAIL_FROM_ADDRESS = self.SMTP_FROM.strip()
        return self

    @property
    def smtp_ready(self) -> bool:
        """Are the SMTP settings complete enough to actually send?"""
        return bool(self.SMTP_HOST.strip() and (self.SMTP_USERNAME or self.MAIL_FROM_ADDRESS).strip()
                    and self.SMTP_PASSWORD.strip())

    @property
    def mail_cc_roles_list(self) -> list[str]:
        return [r.strip() for r in self.MAIL_CC_TEAM_ROLES.split(",") if r.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
