"""Google OAuth 2.0 desktop flow for YouTube uploads (Pillar 4).

Usage:
  python scripts/youtube_auth.py status   # show token state
  python scripts/youtube_auth.py login    # run OAuth flow, save refresh token
  python scripts/youtube_auth.py test     # verify token -> who am I
  python scripts/youtube_auth.py revoke   # revoke + delete token

Token persistence: data/yt_token.json (atomic write, headless re-use).
Client secret discovery: $YT_CLIENT_SECRET env, else ./client_secret*.json
in project root or remotion/.

Dependencies (live mode only): pip install google-auth-oauthlib
google-api-python-client  (imports are lazy so dry-runs work without them)
"""

import argparse
import contextlib
import glob
import json
import os
import sys

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOKEN_PATH = os.path.join(PROJECT, "data", "yt_token.json")
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def set_token_path(path):
    """Point auth at a channel-specific token file (multi-channel)."""
    global TOKEN_PATH
    TOKEN_PATH = os.path.abspath(path)


def find_client_secret():
    env = os.environ.get("YT_CLIENT_SECRET")
    if env and os.path.exists(env):
        return env
    for pat in (
        os.path.join(PROJECT, "data", "client_secret*.json"),
        os.path.join(PROJECT, "client_secret*.json"),
        os.path.join(PROJECT, "remotion", "client_secret*.json"),
    ):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def load_token():
    if not os.path.exists(TOKEN_PATH):
        return None
    try:
        with open(TOKEN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_token(cred):
    payload = {
        "token": cred.token,
        "refresh_token": cred.refresh_token,
        "token_uri": cred.token_uri,
        "client_id": cred.client_id,
        "client_secret": cred.client_secret,
        "scopes": list(SCOPES),
        "expiry": cred.expiry.isoformat() if cred.expiry else None,
    }
    tmp = TOKEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    os.replace(tmp, TOKEN_PATH)
    with contextlib.suppress(OSError):
        os.chmod(TOKEN_PATH, 0o600)


def get_credentials():
    """Return valid google.oauth2.credentials.Credentials or None."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("ERROR: google libs missing. Install:")
        print("  pip install google-auth-oauthlib google-api-python-client")
        return None
    data = load_token()
    if data and set(SCOPES) - set(data.get("scopes", [])):
        print("WARN token missing scopes:", list(set(SCOPES) - set(data.get("scopes", []))))
        print("  Re-login needed for full access (portal se AUTH karo)")
    cred = (
        Credentials(**{k: data[k] for k in ("token", "refresh_token", "token_uri", "client_id", "client_secret")})
        if data
        else None
    )
    if cred and not cred.valid:
        try:
            cred.refresh(Request())
            save_token(cred)
        except Exception as e:
            print("token refresh failed:", e)
            return None
    return cred


def cmd_login():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: pip install google-auth-oauthlib google-api-python-client")
        return 1
    secret = find_client_secret()
    if not secret:
        print("client_secret*.json NOT FOUND.")
        print("Put Google Cloud OAuth Desktop credentials at project root")
        print("or set YT_CLIENT_SECRET env var.")
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
    with open(secret, encoding="utf-8-sig") as fh:
        secret_kind = list(json.load(fh).keys())[0]
    if secret_kind == "web":
        redirect_port = 8976
        print(
            f"web-type secret detected: console me ye URI registered hona chahiye -> http://localhost:{redirect_port}/"
        )
        cred = flow.run_local_server(host="localhost", port=redirect_port, prompt="consent", access_type="offline")
    else:
        cred = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not cred.refresh_token:
        print(
            "WARN: no refresh_token returned - headless re-use will fail."
            " Re-run with prompt=consent after revoking app access."
        )
    save_token(cred)
    print("token saved:", TOKEN_PATH)
    return 0


def cmd_test():
    cred = get_credentials()
    if not cred:
        return 1
    try:
        from googleapiclient.discovery import build

        yt = build("youtube", "v3", credentials=cred)
        r = yt.channels().list(part="snippet", mine=True).execute()
        items = r.get("items", [])
        if not items:
            print("token OK but no YouTube channel on this account")
            return 1
        print("channel:", items[0]["snippet"]["title"], "| id:", items[0]["id"])
        return 0
    except Exception as e:
        print("API test failed:", e)
        return 1


def cmd_revoke():
    data = load_token()
    if data and data.get("token"):
        with contextlib.suppress(ImportError):
            import requests  # noqa: F401
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            cred = Credentials(
                **{k: data[k] for k in ("token", "refresh_token", "token_uri", "client_id", "client_secret")}
            )
            cred.revoke(Request())
            print("revoked at Google")
        except Exception as e:
            print("revoke call skipped/failed:", e)
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)
        print("local token deleted")
    return 0


def main():
    ap = argparse.ArgumentParser(description="YouTube OAuth token manager (multi-channel ready)")
    ap.add_argument("cmd", nargs="?", default="status", choices=["status", "login", "test", "revoke"])
    ap.add_argument(
        "--token", default=None, help="token json path, e.g. data/yt_token_channel1.json (default: data/yt_token.json)"
    )
    args = ap.parse_args()
    if args.token:
        set_token_path(args.token)
    cmd = args.cmd
    if cmd == "login":
        return cmd_login()
    if cmd == "test":
        return cmd_test()
    if cmd == "revoke":
        return cmd_revoke()
    data = load_token()
    secret = find_client_secret()
    print("token file :", TOKEN_PATH, "->", "present" if data else "missing")
    if data:
        print("  scopes   :", ", ".join(data.get("scopes", [])))
        print("  expiry   :", data.get("expiry"))
        print("  refresh? :", bool(data.get("refresh_token")))
    print("client sec.:", secret or "NOT FOUND")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
