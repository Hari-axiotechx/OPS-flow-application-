"""python tests/test_voice_stt.py  - token endpoint (Deepgram is mocked; no network)."""
import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import voice_stt

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f"  {extra}"))
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)

# no key -> disabled, never calls the network
voice_stt._get = lambda n, d="": ""
check("disabled without key", voice_stt.enabled() is False)

# key present, token granted (mock)
voice_stt._get = lambda n, d="": {"DEEPGRAM_API_KEY": "secret-key"}.get(n, d)
calls = []
voice_stt._grant = lambda: (calls.append(1) or ("TEMP.TOKEN", 600))
t1 = voice_stt.temp_token(); t2 = voice_stt.temp_token()
check("token returned", t1 and t1[0] == "TEMP.TOKEN")
check("token cached (one grant call)", len(calls) == 1, calls)

url = voice_stt.build_url(["Stylo PG Desk", "deployment", "deployment", "QA"])
check("url has model", "model=nova-3" in url)
check("url has language", "language=en-IN" in url)
check("url streams interim words", "interim_results=true" in url)
check("app name is a keyterm", "keyterm=Stylo%20PG%20Desk" in url, url)
check("keyterms de-duplicated", url.count("keyterm=deployment") == 1)
check("real API key never in url", "secret-key" not in url)

# endpoint (auth mocked)
import app.auth_helpers as ah
ah.require_auth = lambda ctx: object()
r = voice_stt.handle_voice_stt_token(None, {}, None)
check("endpoint enabled", r.get("enabled") is True and r["token"] == "TEMP.TOKEN" and r["url"].startswith("wss://api.deepgram.com/v1/listen?"), r)
check("endpoint never returns the API key", "secret-key" not in str(r))
voice_stt._get = lambda n, d="": ""
check("endpoint disabled without key", voice_stt.handle_voice_stt_token(None, {}, None) == {"enabled": False})
print(f"\nRESULT: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
