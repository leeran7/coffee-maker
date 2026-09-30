"""Token loading, proactive refresh, and account-id extraction.

Reads the credentials written by `codex login` (~/.codex/auth.json).
Refresh tokens are single-use/rotating server-side, so refresh is guarded
by an exclusive file lock: only one refresher may own the file at a time.
"""

import base64
import fcntl
import json
import os
import time
import urllib.parse
import urllib.request

AUTH_FILE = os.path.expanduser("~/.codex/auth.json")
LOCK_FILE = AUTH_FILE + ".lock"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REFRESH_SKEW_SECONDS = 300  # refresh when <5 min of access-token life remains


class AuthError(Exception):
    pass


def _b64url_decode(segment):
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def jwt_payload(token):
    """Decode a JWT payload without verifying (we only read claims)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        return json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception:
        return {}


def _find_tokens(doc):
    """Tolerate a few auth.json shapes; return the dict holding tokens."""
    if not isinstance(doc, dict):
        return None
    for candidate in (doc, doc.get("tokens"), doc.get("auth")):
        if isinstance(candidate, dict) and candidate.get("access_token"):
            return candidate
    return None


def load_tokens():
    """Return (tokens_dict, full_doc). Raises AuthError when not signed in."""
    if not os.path.exists(AUTH_FILE):
        raise AuthError(
            f"no credentials at {AUTH_FILE} — run `codex-sub login` first"
        )
    with open(AUTH_FILE, "r", encoding="utf-8") as f:
        doc = json.load(f)
    tokens = _find_tokens(doc)
    if not tokens or not tokens.get("access_token"):
        raise AuthError(
            f"no access_token in {AUTH_FILE} — run `codex-sub login` first"
        )
    return tokens, doc


def _save_doc(doc):
    tmp = AUTH_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f)
        f.write("\n")
    os.replace(tmp, AUTH_FILE)
    try:
        os.chmod(AUTH_FILE, 0o600)
    except OSError:
        pass


def needs_refresh(access_token, skew=REFRESH_SKEW_SECONDS):
    exp = jwt_payload(access_token).get("exp")
    if not isinstance(exp, (int, float)):
        return True  # can't read expiry: refresh to be safe
    return time.time() > exp - skew


def _post_refresh(refresh_token):
    payload = {
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    last_error = None
    # Try JSON body first (documented community shape), then form-encoded.
    for content_type, body in (
        ("application/json", json.dumps(payload).encode()),
        (
            "application/x-www-form-urlencoded",
            urllib.parse.urlencode(payload).encode(),
        ),
    ):
        req = urllib.request.Request(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.loads(res.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - fall through to next encoding
            last_error = e
            continue
        if data.get("error"):
            last_error = AuthError(
                f"refresh rejected: {data.get('error_description') or data['error']}"
            )
            continue
        if not data.get("access_token"):
            last_error = AuthError(f"refresh returned no access_token: {data!r}"[:200])
            continue
        return data
    raise AuthError(f"token refresh failed: {last_error}")


def refresh_now():
    """Force a token refresh under an exclusive lock. Returns fresh tokens."""
    with open(LOCK_FILE, "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            tokens, doc = load_tokens()
            rt = tokens.get("refresh_token")
            if not rt:
                raise AuthError("no refresh_token stored — sign in again")
            data = _post_refresh(rt)
            tokens["access_token"] = data["access_token"]
            if data.get("refresh_token"):
                tokens["refresh_token"] = data["refresh_token"]  # rotation
            if data.get("id_token"):
                tokens["id_token"] = data["id_token"]
            tokens["refreshed_at"] = int(time.time())
            _save_doc(doc)
            return tokens
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def ensure_fresh_tokens():
    """Load tokens, refreshing proactively when close to expiry."""
    tokens, _ = load_tokens()
    if needs_refresh(tokens["access_token"]):
        return refresh_now()
    return tokens


def account_id(access_token):
    """ChatGPT account id for the ChatGPT-Account-ID header."""
    payload = jwt_payload(access_token)
    nested = payload.get("https://api.openai.com/auth") or {}
    return (
        (nested.get("chatgpt_account_id") if isinstance(nested, dict) else None)
        or payload.get("chatgpt_account_id")
        or payload.get("sub")
    )


def token_expiry(access_token):
    exp = jwt_payload(access_token).get("exp")
    if isinstance(exp, (int, float)):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp))
    return "unknown"
