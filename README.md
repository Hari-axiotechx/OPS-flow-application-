<<<<<<< HEAD
# OPSFlow

A deployment / access-request / issue-tracking tool for Dev, QA and DevOps
teams.

This version replaces the original **Google Sheets + Apps Script** backend
with a proper **FastAPI + PostgreSQL** backend, fully dockerized. The React
frontend is run **manually** (`npm install` / `npm run dev`) on your laptop
and is not part of the Docker setup — it was already written against a
simple `action`-based HTTP API, and the new backend speaks the exact same
contract, so it only needs to point at the backend's URL.

```
opsflow/
├── backend/          FastAPI + PostgreSQL API (replaces Code.gs) — Dockerized
├── frontend/         React + Vite app — run manually, NOT containerized
└── docker-compose.yml
```

## Run backend + database with Docker

Requires Docker Desktop (or Docker Engine + Compose) on your laptop.

```bash
cd opsflow
docker compose up --build
```

This starts two containers:

| Service    | URL                              | What it is                          |
|------------|-----------------------------------|--------------------------------------|
| `db`       | localhost:5432                    | PostgreSQL 16                        |
| `backend`  | http://localhost:8000/api         | FastAPI                              |

On first startup the backend automatically:
- creates all tables,
- seeds the default config values (apps, environments, access types),
- creates a first **Admin** login:
  `hariprasad.mylamuru@axiotechx.com` / `Hari123!`
  (override via `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `docker-compose.yml`
  before first run). **Change this password after logging in.**
- restricts self-registration to `@axiotechx.com` email addresses only
  (override/disable via `ALLOWED_EMAIL_DOMAIN` in `docker-compose.yml`).
- DevOps admins with admin power can also create active users directly from
  **User Management** by setting an initial password; OPSFlow emails an account
  notification without sending the password.

To stop: `Ctrl+C`, then `docker compose down` (add `-v` to also wipe the
database volume and start fresh).

## Run the frontend manually (not in Docker)

With the `backend` container above running on `http://localhost:8000`:

```bash
cd frontend
npm install
cp .env.example .env    # VITE_API_URL=/api uses the Vite proxy to reach the backend
npm run dev
```

Open **http://localhost:5173** in your browser.

## Running the backend without Docker

**Postgres:** install locally or run just the `db` service:
```bash
docker compose up db
```

**Backend:**
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # edit DATABASE_URL if needed
uvicorn app.main:app --reload --port 8000
```

## What changed from the Google Sheets version

- **Storage:** every "sheet" (Users, Deployments, Access Requests, Issue
  Tracker, Production Issues, Audit Log, Config) is now a proper Postgres
  table — see `backend/app/models.py`. `db/schema.sql` only creates tables
  (IF NOT EXISTS); it never deletes rows or drops columns.
- **Business logic:** every handler (create/approve/reject deployments,
  access requests, issues, production issues, user approval, config,
  audit trail, deployment time-conflict detection, status-transition
  rules) was ported one-for-one from the old `Code.gs` into
  `backend/app/logic.py`. Behavior should match exactly.
- **Auth:** passwords are now hashed with bcrypt (previously a plain
  SHA-256), sessions still use a signed, stateless token the frontend
  stores in `localStorage`, same as before.
- **Record IDs:** still human-readable (`DEP-000123`, `USR-000045`, ...),
  now generated from a Postgres sequence-like counter table instead of
  scanning a spreadsheet column.
- **API contract:** unchanged. Same single endpoint, same `action` field,
  same request/response shapes — the frontend didn't need any code
  changes, only a new `VITE_API_URL`.
- **Not carried over:** the old backend emailed password-reset codes via
  Google's `MailApp`. This backend logs the OTP to the console instead
  (see `handle_request_password_reset` in `backend/app/logic.py`) — wire
  up a real SMTP/email provider there before relying on password reset in
  production.

## Environment variables (backend)

See `backend/.env.example`. The important ones:

- `DATABASE_URL` — Postgres connection string
- `TOKEN_SECRET` — signs session tokens; set a long random value before
  deploying anywhere other than your own laptop
- `CORS_ORIGINS` — comma-separated list of origins allowed to call the API
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_NAME` — first-run admin account
- `ALLOWED_EMAIL_DOMAIN` — only emails ending in this domain can register
  (default `axiotechx.com`; leave blank to allow any domain)

## Changelog — notifications, applications, bug fixes

**New**
- 🔔 Notification bell (top-right): yellow bell, red badge with unread
  count, auto-refresh every 15 s, toast on new items, click to open the
  record, "Mark all read". Stored in Postgres (`notifications` table).
  - New deployment / access request / production issue → all DevOps users
  - Status change → requester (+ assigned DevOps)
  - Reassign / request reassignment → target DevOps user
  - New registration → admins; approval → that user
  - New application → everyone
- 🧩 Applications page (`/applications`, admin only — Sidebar → Admin →
  Applications, or Dashboard + New → New Application). List on top, form
  at the bottom (name, date, Submit). New apps appear instantly in the
  Deployment / Access / Production Issue dropdowns for all roles.

**Removed**
- Issue Tracker (pages, "+ New → New Issue", dashboard lists, search).

**Fixed**
- `serializers.py` was a copy of `logic.py` → circular import, backend
  could not start. Restored.
- Rollback branch not saved / not returned. Fixed; missing
  `rollback_branch` column is added automatically on startup.
- Dashboard + New links (`?new=1`) did nothing; broken `/issues` link;
  role-appropriate options only.
- Tailwind `ink-50/100/300/500` colours were used but not defined.
- Notifications were stored in the sender's localStorage; now server-side.

No manual migration needed — new tables are created on startup.


## E-mail notifications (Outlook / Microsoft 365)

OPSFlow e-mails DevOps when a deployment request, access request or AWS issue
is raised, and e-mails the admins when a new user registers.

| Event | To | Cc |
|---|---|---|
| Deployment request | all DevOps (admins + engineers) | requester + Developers + QA |
| AWS issue | all DevOps | reporter + Developers + QA |
| Access request | all DevOps | requester |
| New user registration | DevOps admins | - |
| **Deployment deployed successfully / failed / rolled back** | requester + assigned DevOps + admin(s) | everyone else (and the person who changed the status) |

* E-mail is always enabled on the server; request forms do not offer an enable/disable switch.
* Account preferences and per-request flags cannot disable e-mail.
* Environment-variable **values are never e-mailed** (only the names).

### Set up
1. Copy the `MAIL_*` and `GRAPH_*` lines into a `.env` file next to
   `docker-compose.yml`. E-mail is always enabled and uses Microsoft Graph.
2. Register an app in Entra ID, add the *Mail.Send* application permission,
   grant admin consent, and fill in the `GRAPH_*` values. SMTP is not used as
   a fallback when Graph fails.
3. `docker compose up -d --build`, then test:
   `docker compose exec backend python -m app.mailer you@axiotechx.com`

### Deployment outcome e-mails (new)
When a DevOps user moves a deployment to **Deployed successfully**, **Deployment failed** or
**Rolled back**, an e-mail is sent automatically (green / red / amber header, project, environment,
version/branch, who changed it, and the failure or rollback reason). Approvals / rejections do not send
this success/failure/rollback e-mail; rejection sends its own notification. Code:
`deployment_outcome()` in `backend/app/email_events.py`, called from `handle_update_deployment_status`.

## Voice assistant (new)

A mic button sits beside the search box on every page. Click it and talk. **Hands-free is ON by default**
(turn it off in the assistant panel if you do not want the microphone listening for a wake phrase): say
**"Hello Ops"** or **"Hey Ops"** and it greets you by first name, then listens. You can also say a command
in the same breath, for example "Hello Ops, open deployment 123"; it runs after the greeting.

Examples: *open deployment 123 · show failed deployments · show prod deployments today · how many pending
access requests · show my deployments · approve deployment 123 · roll back deployment 125 · create a new
deployment · search stylo · give me a summary · go to dashboard · who am I · log out · thank you*.
After a list appears you can say "open the second one".

* Status changes by voice (approve / reject / start / success / fail / roll back) are **always confirmed out
  loud** ("Shall I approve deployment 123? Say yes or no"); reject / fail / roll back also ask for the reason.
  They go through the normal API, so permissions, audit trail and e-mails behave exactly as with the buttons.
* Needs **Chrome or Edge** (speech recognition) and `https://` or `localhost`. The first time, allow the
  microphone. The "Hands-free" switch in the assistant panel turns "Hello Ops" listening off.
  Note: Chrome / Edge send microphone audio to their cloud speech service while the mic is listening.
* Free-form AI understanding requires `ANTHROPIC_API_KEY` (see `.env.example`). Without it, the built-in
  parser still handles supported commands, but cannot interpret arbitrary requests.
* Code: `backend/app/voice.py` (action `voiceCommand`), `frontend/src/components/voice/VoiceAssistant.jsx`,
  `frontend/src/voice/*`. Tests: `python backend/tests/test_voice_and_emails.py`.

## Voice assistant ("Hello Ops")

After login, saying **"Hello Ops"** or **"Hey Ops"** opens the assistant and speaks a personalized
**"Hi [first name], how can I help you?"** greeting before listening for a request. Hands-free is on by
default (switch it off in the assistant panel).

| You say | What happens |
|---|---|
| "Create a deployment request" | The real form opens. The assistant asks one question at a time (application, frontend/backend, environment, date and time, GitHub URL, branch, rollback branch, DB / API / env-var changes...) and **types every answer into the form on screen**. |
| "Deploy Stylo PG Desk backend to production tomorrow at 10 PM" | One sentence can fill several fields at once. |
| "I need access to S3" / "Raise an access request" | Same guided flow for access requests. |
| "Report an AWS issue" (DevOps) | Same guided flow for AWS issues. |
| "Add a new application" (admin) | Types the name into the Applications page. |
| "Change the environment to QA" | Corrects a field. |
| "What's left?" / "Cancel" | Progress / close the form. |
| "Open deployment 123", "Show failed deployments", "Approve deployment 5" | Existing commands (unchanged). |

**The assistant never submits.** When everything required is filled it says so and you click
**Submit Request** yourself. Files (DB / schema change) are attached by you with the upload button.

### Requirements
* Chrome or Edge, microphone allowed, and the app opened over **https://** (or `localhost`):
  `npm i` then `npm run dev` serves `https://<your-ip>:5173` (self-signed, accept the warning once).
* Set `ANTHROPIC_API_KEY` for the backend (docker-compose already passes it through) to enable free-form
  AI questions, look-ups, and follow-ups. Without a key, the built-in rule parser handles supported commands only.
  Uploaded files and environment-variable values are never sent to the model.

### Where the code is
```
backend/app/voice.py          commands ("open", "list", "approve", "create ...")
backend/app/voice_form.py     guided form conversation (NEW)       -> action voiceForm
backend/tests/test_voice_form.py                                     python tests/test_voice_form.py
frontend/src/voice/engine.js  wake word, listening / speaking loop, form conversation (NEW)
frontend/src/voice/voiceForms.js + useVoiceForm.js   bridge between assistant and forms (NEW)
frontend/src/components/voice/VoiceAssistant.jsx     panel + live checklist
frontend/src/pages/{DeploymentRequests,AccessRequests,AwsIssues,Applications}.jsx   register their form
```

## Voice assistant v2 — faster and smarter

### Speed
| Before | Now |
|---|---|
| Wake word with no personalized greeting | Greets the signed-in user by first name; a command said in the same breath is retained and handled after the greeting |
| Waited for the browser's own end-of-sentence (often 1–2 s) | Own end-of-speech detection: **~0.45 s** after you stop; waits longer only when the sentence clearly continues ("open deployment …", "assign it to …") |
| Every command went to the server | "go to dashboard", "go back", "open deployment 123" act **in the browser immediately**; the spoken answer follows |
| A new TLS connection to the AI on every sentence | Keep-alive connection pool (`backend/app/llm.py`), **warmed up the moment you say "Hello Ops"** |
| Backend ran voice/AI work inside the async event loop — one slow AI call froze every user's requests | All API actions run in the thread pool (`main.py`) |
| Speech rate 1.0, voice re-picked every time, 60 ms delay, 350 ms pause | Rate 1.12, cached voice (prefers local voices), no delay, 100 ms pause |
| Silence → "I didn't catch that…" spoken | Closes quietly with a soft chime |
| 2.2 s splash screen on every page load | 0.5 s, once per browser tab |

### Understanding ("like an AI")
* **Context** — it knows the record on screen and the last record you talked about:
  "approve it", "reject this one", "who requested it?", "assign it to me", "open it".
* **Questions about records** answered from real data (no AI key needed):
  "who requested deployment 12?", "who is assigned?", "when is it scheduled?", "why did it fail?",
  "which branch?", "tell me about deployment 125".
* **Changes by voice** (always confirmed, same permission rules as the buttons):
  status changes, "set the rollback branch of deployment 12 to release slash 1.0" (DevOps),
  "assign deployment 12 to Eswar" (admin).
* **AI agent** (set `ANTHROPIC_API_KEY`): anything the rules don't fully understand goes to Claude, which
  remembers the conversation, **looks things up** (read-only tools: get_record / find_records / search_records)
  and then picks one action or speaks an answer built only from real data. E.g.
  "did anything go wrong with the PG Desk releases this week?", "what has Keshava pushed to prod lately?",
  "okay approve the stylo one". It can never do more than the UI buttons allow, and secrets
  (env-var values, uploaded files) are never sent to the model.
  Simple commands never wait for the AI.

Tests: `python tests/test_voice_ai.py` (context, questions, edits, assign, AI agent with a mocked model),
plus the existing `test_voice_and_emails.py` and `test_voice_form.py`.

Tuning: end-of-speech timings are at the top of `frontend/src/voice/engine.js` (`END_AFTER_FINAL` etc.);
the speaking rate is `SPEECH_RATE` in `frontend/src/voice/speech.js`.


## Voice assistant v3 - "Hello Ops" + speed (latest)

* **Wake phrases:** "Hello Ops" and "Hey Ops". Recent speech-recognition segments are checked together so
  phrases split across recognition results still activate the assistant. The assistant speaks a personalized greeting.
* **Faster form answers:** short direct answers ("production", "backend", "tomorrow 10 PM") are understood by the
  built-in rules instantly; the AI is only called when the rules cannot understand the answer (`voice_form.py`).
* **Faster AI agent:** max 3 steps (was 4), 5 s timeout (was 7), 300 max tokens, shorter history (`voice.py`).
* **Faster listening:** end-of-speech 0.3 s after you stop (`END_AFTER_FINAL` in `engine.js`); speech rate 1.18;
  0.06 s pause before the mic re-opens.
* **No dead silence:** if the server needs more than 0.7 s a soft tick sounds so you know it is working.
* Model: `VOICE_LLM_MODEL=claude-haiku-5-5` (the fastest). Keep it.

### v3.1 - clearer listening, no wrong cut-offs
* Needs `frontend/.env` containing `VITE_API_URL=/api` (copy `.env.example`), then restart `npm run dev`.
* The browser's 5 alternative guesses per sentence are scored against the assistant's vocabulary; the best one is used (`bestTranscript` in `wake.js`).
* Common mis-hearings are corrected for commands ("deploy meant" -> deployment, "a prove" -> approve, "q a" -> qa ...) (`fixSpeech`).
* End-of-speech waits restored to 0.4 s / 1.0 s / 1.6 s so it does not cut you off mid-sentence.
* Vite proxy now targets `127.0.0.1` (on Windows `localhost` can try IPv6 first and add a delay to every request).
* Console shows `[voice] heard=... total=...ms server=...ms source=rules|ai` for every command.

## Voice assistant v5 - professional listening (Deepgram)

The browser's built-in recognizer is the main cause of slow / unclear listening. v5 can use **Deepgram Nova-3**
(streaming speech-to-text) for commands. It is optional: with no key everything works as before.

1. Create a free key at https://console.deepgram.com and put it in `.env` next to `docker-compose.yml`:
   `DEEPGRAM_API_KEY=your_key` (optional: `STT_MODEL=nova-3`, `STT_LANGUAGE=en-IN`).
2. `docker compose up -d --build`, restart `npm run dev`, hard-refresh the page.
3. Say "Hello Ops". Open the browser console (F12): you should NOT see "speech service unavailable".

How it works: "Hello Ops" is still detected by the browser (free, so nothing is streamed to the cloud while idle).
At that moment the page hands over to Deepgram, whose connection was opened in advance, so nothing you say is lost.
Words appear while you speak. Your application names are sent as `keyterm`s so they are recognised correctly.
The real API key stays on the server; the browser only gets a 10-minute token (`voiceSttToken`).
If Deepgram fails, the assistant falls back to the browser recognizer for a minute automatically.

Code: `backend/app/voice_stt.py`, `frontend/src/voice/stt.js`, hooks in `frontend/src/voice/engine.js`.
Tests: `python backend/tests/test_voice_stt.py`.

## Voice assistant v6 - 1-minute listening, louder mic, faster answers

* **Listens for 1 minute** after "Hello Ops" and after every answer (`LISTEN_WINDOW_MS` in `engine.js`). If the browser
  stops its listening session early, it silently starts listening again until the minute is over.
* **Louder microphone** for the Deepgram recognizer: gain x2.5 + compressor (`MIC_GAIN` in `stt.js`; raise to 3.5 if still too quiet).
* **AI answers capped at ~4 s** and at most 2 AI calls per sentence (`budget` in `agent_plan`, `voice.py`). If the AI is
  slower, the built-in rules answer instead.
* The soft "working" tick now sounds after 0.3 s.

## Voice assistant v7 - quiet voices, distance, faster replies

* **Hear a quiet / distant voice:** set `STT_WAKE=cloud` (with `DEEPGRAM_API_KEY`). Then Deepgram - with the x4 boosted
  microphone - listens for "Hello Ops" too, not just for the command. (Uses Deepgram audio minutes while the page is open.)
* The panel header now shows which listener is active: **clear voice engine** (Deepgram) or **browser voice (basic)**.
  If it says "basic", Deepgram is not set up (key missing / token failed) - see the browser console (F12).
* **Answers right after you stop talking** (Deepgram end-of-speech), instead of waiting an extra 0.4 s.
* **Long answers are only partly read aloud** (first ~230 characters); the panel shows the full text.
* Windows microphone tip: Settings > System > Sound > Input > your mic > Properties: volume 100 and "Microphone boost" +20 dB.

## v8 notes (voice navigation fix)
- Wake words: "Hello Ops" and "Hey Ops" (also "OK Ops").
- While a form is open you can now say, at any time:
  - "open profile", "go to dashboard", "go back to deployments" -> closes the form popup and opens that page.
  - "go back" / "previous question" / "undo" -> ONE step back inside the form (clears the last answer and asks it again). At the very first question it closes the form.
  - "review" -> reads every filled field out loud in full, then tells you to click Submit yourself.
  - "cancel", "close the form" -> closes the form. "close the assistant" / "stop listening" -> voice off, form stays open.
- After you click Submit the form conversation ends, so "go back", "open profile", etc. work normally.

## E-mail notifications
E-mail is always enabled. There is no user-facing or environment-variable enable/disable
control, and legacy account preferences or request flags cannot suppress e-mail.

| Event | To | Cc |
|---|---|---|
| New deployment request | Admin(s) | DevOps, Developers, QA, requester |
| Deployed successfully / FAILED / ROLLED BACK | requester + assigned DevOps + admin(s) | everyone else + the person who changed the status |
| New access request | Admin(s) | everyone else |
| New user registration | DevOps admins | - |
| AWS issue | selected recipients | selected recipients |

At least one **To** recipient is required for request forms. Configure SMTP or Graph credentials
for actual delivery.
Keep `.env` private: it holds the SES SMTP password. Do not commit it or share it.

## v9 changes (UI)
- Deployment / Access / AWS-issue status filters are now MULTI-select: click as many chips as you like (e.g. Approved + In Progress + Failed); click again to remove; "All" clears. The choice lives in the URL (`?status=APPROVED,IN_PROGRESS`), old single links still work.
- Back arrow now sits in FRONT of the page title / record id (`←  DEP-000030`) on every page (not on the Dashboard); the old arrow above the page is gone.
- Deployment detail shows a progress flow under the header: Requested → Approved → In Progress → Success | Failed | Rolled back (or Requested → Rejected), with who/when from the audit trail.
- "Rollback Branch" is no longer mandatory (form, server and voice assistant). The voice assistant asks for it in the optional "anything else?" question.


---

## v12 — mandatory e-mail for Deployment & Access requests, reliable sending

**What changed**

* **All request and outcome e-mails are always enabled.** No account preference or legacy `sendEmail=false` request flag can suppress them. The To / Cc boxes are shown, "To" is required, and DevOps admins are pre-filled for mandatory requests.
* **If the picked people cannot be resolved, the e-mail goes to the DevOps admin(s)** instead of being dropped.
* **One unverified address can no longer block everyone.** With AWS SES in sandbox mode a single unverified recipient makes SES reject the whole message. OPSFlow now re-sends to each person separately, so everyone who *can* receive it, does.
* **Failures are no longer silent.** Sending is retried (`MAIL_RETRIES`, default 3). If it still fails, the requester gets a bell notification with the real reason (and a link to the request). The "created" message now says who the e-mail is being sent to.
* **Startup check:** `docker compose logs backend` now prints the e-mail settings and whether the SMTP login works, right when the backend starts.
* **Admin "Email check"** on the Profile page sends a real test e-mail immediately and shows the mail server's exact answer.
* The recipient list refreshes each time a form opens (newly approved people appear without a reload).
* Port 465 (implicit TLS) is supported as well as 587 (STARTTLS).

**Microsoft Graph set-up (MAIL_PROVIDER=graph)**

1. In Microsoft Entra ID, register an app. Copy the *Directory (tenant) ID* and *Application (client) ID*.
2. Create a client secret and copy its **Value** (not the Secret ID) right away.
3. API permissions → Microsoft Graph → **Application permissions** → `Mail.Send` → **Grant admin consent**.
4. `MAIL_FROM_ADDRESS` (no-reply@axiotechx.com) must be a real mailbox or shared mailbox in your tenant.
5. Put the three values in the `.env` next to `docker-compose.yml` (`GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`), then `docker compose up -d --build`.

**If e-mails still do not arrive**

* The backend log and the admin test button now translate Microsoft's answer: empty settings, wrong secret (secret ID pasted instead of the value, or expired), 403 = Mail.Send / admin consent missing, 404 = sender mailbox does not exist.
* (SMTP / AWS SES only) in SES sandbox mode the sender and every recipient must be verified.

Use Profile → Email check (admin) or `docker compose exec backend python -m app.mailer you@axiotechx.com` to see which one it is.

Tests: `python tests/test_mailer.py` (SES sandbox simulation, retries, failure reporting) and `python tests/test_selected_recipients.py`.
=======
# OPS-flow-application-
This is used to devops engineer application Developer and QA request to the deployment through this application 
>>>>>>> d7f62f3a87d9ab7d41277bd502bed331dc9028e7
