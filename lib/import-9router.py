#!/usr/bin/env python3
"""Batch-import CLIProxyAPI Codex OAuth JSON files into 9router's SQLite.

Source: a directory of `codex-<email>-<plan>.json` files (the CLIProxyAPI auth
file format). Each file holds: access_token, refresh_token, id_token,
account_id, email, expired, type=codex, ...

Destination: 9router's `providerConnections` SQLite table at
~/.9router/db/data.sqlite. Schema:
  id, provider, authType, name, email, priority, isActive, data(JSON), createdAt, updatedAt

The `data` JSON mirrors the shape 9router writes itself, including
`providerSpecificData.{chatgptAccountId, chatgptPlanType}`.

Dedup rule: skip rows where (provider='codex' AND email=...) already exists.
"""
from __future__ import annotations
import argparse, base64, datetime as dt, json, os, pathlib, sqlite3, sys, uuid

def b64url(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def jwt_claims(id_token: str) -> dict:
    parts = id_token.split(".")
    if len(parts) < 2:
        return {}
    try:
        return json.loads(b64url(parts[1]))
    except Exception:
        return {}

def to_utc_z(ts: str) -> str:
    """Convert any ISO-8601 (with or without offset) to UTC ISO with Z."""
    t = dt.datetime.fromisoformat(ts)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def transform(auth: dict) -> dict:
    claims = jwt_claims(auth.get("id_token", ""))
    chatgpt = claims.get("https://api.openai.com/auth") or {}
    chatgpt_account_id = chatgpt.get("chatgpt_account_id") or auth.get("account_id")
    chatgpt_plan_type  = chatgpt.get("chatgpt_plan_type")  or "free"

    expired = auth.get("expired") or ""
    if expired:
        expires_at = to_utc_z(expired)
        try:
            t = dt.datetime.fromisoformat(expired).astimezone(dt.timezone.utc)
            expires_in = int((t - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except Exception:
            expires_in = 0
    else:
        expires_at = ""
        expires_in = 0

    return {
        "accessToken": auth.get("access_token", ""),
        "refreshToken": auth.get("refresh_token", ""),
        "idToken": auth.get("id_token", ""),
        "expiresAt": expires_at,
        "expiresIn": expires_in,
        "testStatus": "active",
        "lastError": None,
        "lastErrorAt": None,
        "lastUsedAt": None,
        "consecutiveUseCount": 0,
        "backoffLevel": 0,
        "errorCode": None,
        "providerSpecificData": {
            "chatgptAccountId": chatgpt_account_id,
            "chatgptPlanType": chatgpt_plan_type,
        },
    }

def main() -> int:
    if os.environ.get("ALLOW_UNSAFE_9ROUTER_CODEX_IMPORT") != "1":
        sys.exit("DISABLED: importing Codex OAuth into 9Router creates a second refresher risk. Keep CLIProxyAPI as the single owner, or set ALLOW_UNSAFE_9ROUTER_CODEX_IMPORT=1 for forensic-only use.")
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="directory of codex-*.json")
    ap.add_argument("--db", required=True, help="path to 9router data.sqlite")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = pathlib.Path(args.src)
    if not src.is_dir():
        sys.exit(f"src not a directory: {src}")

    files = sorted(src.glob("codex-*.json"))
    if not files:
        print(f"no codex-*.json files in {src}")
        return 0

    con = sqlite3.connect(args.db, timeout=10, isolation_level=None)
    con.execute("PRAGMA busy_timeout=5000;")
    cur = con.cursor()

    # Existing emails for codex
    cur.execute("SELECT email FROM providerConnections WHERE provider='codex'")
    existing = {row[0] for row in cur.fetchall() if row[0]}
    cur.execute("SELECT COALESCE(MAX(priority),0) FROM providerConnections WHERE provider='codex'")
    max_priority = cur.fetchone()[0] or 0

    inserted = skipped_dup = skipped_bad = 0
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    for f in files:
        try:
            auth = json.loads(f.read_text())
        except Exception as e:
            skipped_bad += 1
            print(f"  ✗ {f.name}: invalid JSON ({e})")
            continue

        if auth.get("type") and auth["type"] != "codex":
            skipped_bad += 1
            print(f"  ✗ {f.name}: type={auth.get('type')!r} (not codex)")
            continue

        email = auth.get("email") or ""
        if not email:
            skipped_bad += 1
            print(f"  ✗ {f.name}: missing email")
            continue
        if not auth.get("refresh_token"):
            skipped_bad += 1
            print(f"  ✗ {f.name}: missing refresh_token")
            continue

        if email in existing:
            skipped_dup += 1
            continue

        data_obj = transform(auth)
        max_priority += 1
        row = (
            str(uuid.uuid4()),
            "codex",
            "oauth",
            email.split("@")[0],
            email,
            max_priority,
            1,
            json.dumps(data_obj, separators=(",", ":")),
            now,
            now,
        )
        if args.dry_run:
            print(f"  + would insert: {email} (priority={max_priority})")
        else:
            cur.execute(
                """INSERT INTO providerConnections
                   (id, provider, authType, name, email, priority, isActive, data, createdAt, updatedAt)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                row,
            )
            existing.add(email)
            inserted += 1

    con.close()
    print(f"Done. inserted={inserted} skipped_dup={skipped_dup} skipped_bad={skipped_bad} total_scanned={len(files)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
