#!/usr/bin/env python3
"""Repair Codex local session metadata after backend/account switches.

Codex keeps raw rollouts under ~/.codex/sessions, but the visible/resumable
thread list is indexed separately in state_5.sqlite and session_index.jsonl.
When cxsw switches model providers, older rows can remain tagged with the old
provider and disappear from provider-filtered UIs. This helper rebuilds the
index and, by default, adopts all local threads to the currently selected
provider so old conversations stay visible across switches.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

SESSION_ID_RE = re.compile(r"rollout-\d{4}-\d{2}-\d{2}T.*-([0-9a-fA-F-]{36})\.jsonl$")
PROVIDER_BY_MODE = {
    "native": "openai",
    "openai": "openai",
    "cliproxy": "cliproxy",
    "9router": "r9router",
    "r9router": "r9router",
}


@dataclass
class Rollout:
    id: str
    path: pathlib.Path
    created_at_ms: int
    updated_at_ms: int
    source: str
    model_provider: str
    cwd: str
    title: str
    first_user_message: str
    preview: str
    sandbox_policy: str
    approval_mode: str
    cli_version: str
    model: str | None
    reasoning_effort: str | None
    thread_source: str | None
    has_user_event: int


def parse_iso_ms(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.astimezone(dt.timezone.utc).timestamp() * 1000)


def iso_from_ms(value: int) -> str:
    parsed = dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def clean_text(value: str, limit: int = 4000) -> str:
    value = value.replace("\x00", "")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = value.strip()
    if len(value) > limit:
        return value[: limit - 3].rstrip() + "..."
    return value


def one_line(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        return value[: limit - 3].rstrip() + "..."
    return value


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "input_text", "message", "content"):
            text = extract_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = extract_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return ""


def id_from_path(path: pathlib.Path) -> str | None:
    match = SESSION_ID_RE.search(path.name)
    return match.group(1) if match else None


def parse_rollout(path: pathlib.Path) -> Rollout | None:
    stat = path.stat()
    meta: dict[str, Any] = {}
    turn_context: dict[str, Any] = {}
    first_event_user = ""
    first_response_user = ""
    first_seen_ms: int | None = None
    last_seen_ms: int | None = None
    has_user_event = 0

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts_ms = parse_iso_ms(obj.get("timestamp"))
                if ts_ms is not None:
                    first_seen_ms = ts_ms if first_seen_ms is None else min(first_seen_ms, ts_ms)
                    last_seen_ms = ts_ms if last_seen_ms is None else max(last_seen_ms, ts_ms)

                payload = obj.get("payload") or {}
                obj_type = obj.get("type")
                payload_type = payload.get("type")

                if obj_type == "session_meta":
                    meta.update(payload)
                    meta_ts_ms = parse_iso_ms(payload.get("timestamp"))
                    if meta_ts_ms is not None:
                        first_seen_ms = meta_ts_ms if first_seen_ms is None else min(first_seen_ms, meta_ts_ms)
                elif obj_type == "turn_context" and not turn_context:
                    turn_context = payload
                elif obj_type == "event_msg" and payload_type == "user_message":
                    has_user_event = 1
                    if not first_event_user:
                        first_event_user = extract_text(payload.get("message")) or extract_text(
                            payload.get("text_elements")
                        )
                elif (
                    obj_type == "response_item"
                    and payload_type == "message"
                    and payload.get("role") == "user"
                ):
                    has_user_event = 1
                    if not first_response_user:
                        first_response_user = extract_text(payload.get("content"))
    except OSError as exc:
        print(f"Warning: cannot read rollout {path}: {exc}", file=sys.stderr)
        return None

    thread_id = safe_str(meta.get("id")) or id_from_path(path)
    if not thread_id:
        return None

    created_ms = parse_iso_ms(meta.get("timestamp")) or first_seen_ms or int(stat.st_ctime * 1000)
    updated_ms = last_seen_ms or int(stat.st_mtime * 1000) or created_ms
    first_user_message = clean_text(first_event_user or first_response_user)
    title = one_line(first_user_message) or thread_id
    preview = clean_text(first_user_message, limit=1000)

    return Rollout(
        id=thread_id,
        path=path,
        created_at_ms=created_ms,
        updated_at_ms=updated_ms,
        source=safe_str(meta.get("source")) or "cli",
        model_provider=safe_str(meta.get("model_provider")) or "openai",
        cwd=safe_str(meta.get("cwd")),
        title=title,
        first_user_message=first_user_message,
        preview=preview,
        sandbox_policy=safe_str(
            turn_context.get("sandbox_policy") or turn_context.get("file_system_sandbox_policy")
        ),
        approval_mode=safe_str(turn_context.get("approval_policy")),
        cli_version=safe_str(meta.get("cli_version")),
        model=safe_str(turn_context.get("model")) or None,
        reasoning_effort=safe_str(turn_context.get("effort")) or None,
        thread_source=safe_str(meta.get("thread_source")) or None,
        has_user_event=has_user_event,
    )


def collect_rollouts(codex_home: pathlib.Path) -> dict[str, Rollout]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.is_dir():
        return {}
    rollouts: dict[str, Rollout] = {}
    for path in sorted(sessions_dir.rglob("*.jsonl")):
        rollout = parse_rollout(path)
        if not rollout:
            continue
        current = rollouts.get(rollout.id)
        if current is None or rollout.updated_at_ms >= current.updated_at_ms:
            rollouts[rollout.id] = rollout
    return rollouts


def resolve_provider(args: argparse.Namespace) -> str | None:
    raw = args.provider or args.mode
    if not raw:
        return None
    return PROVIDER_BY_MODE.get(raw, raw)


def backup_file(src: pathlib.Path, dest: pathlib.Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.name.endswith(".sqlite"):
        src_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        try:
            dst_con = sqlite3.connect(dest)
            try:
                src_con.backup(dst_con)
            finally:
                dst_con.close()
        finally:
            src_con.close()
    else:
        shutil.copy2(src, dest)
    dest.chmod(0o600)


def backup_state(codex_home: pathlib.Path, backup_dir: pathlib.Path | None) -> list[pathlib.Path]:
    if backup_dir is None:
        backup_dir = codex_home / "backups" / "cxsw-sessions"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    out: list[pathlib.Path] = []
    for name in ("state_5.sqlite", "session_index.jsonl"):
        src = codex_home / name
        if not src.exists():
            continue
        dest = backup_dir / f"{name}.{stamp}.bak"
        backup_file(src, dest)
        out.append(dest)
    return out


def backup_rollout(path: pathlib.Path, codex_home: pathlib.Path, backup_dir: pathlib.Path) -> pathlib.Path:
    try:
        rel = path.relative_to(codex_home)
    except ValueError:
        rel = pathlib.Path(path.name)
    dest = backup_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    dest.chmod(0o600)
    return dest


def rewrite_rollout_providers(
    rollouts: dict[str, Rollout],
    provider: str | None,
    codex_home: pathlib.Path,
    backup_dir: pathlib.Path | None,
    dry_run: bool,
) -> tuple[int, list[pathlib.Path]]:
    if not provider:
        return 0, []

    rewritten = 0
    backups: list[pathlib.Path] = []
    for rollout in rollouts.values():
        if rollout.model_provider == provider:
            continue
        rewritten += 1
        if dry_run:
            continue

        path = rollout.path
        fd, tmp_name = tempfile.mkstemp(prefix=".rollout.", suffix=".jsonl", dir=path.parent)
        changed = False
        try:
            with path.open("r", encoding="utf-8", errors="replace") as src, os.fdopen(
                fd, "w", encoding="utf-8"
            ) as dst:
                for line in src:
                    out_line = line
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        dst.write(out_line)
                        continue
                    payload = obj.get("payload")
                    if obj.get("type") == "session_meta" and isinstance(payload, dict):
                        if payload.get("model_provider") != provider:
                            payload["model_provider"] = provider
                            out_line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
                            changed = True
                    dst.write(out_line)

            if changed:
                if backup_dir is not None:
                    backups.append(backup_rollout(path, codex_home, backup_dir))
                os.chmod(tmp_name, path.stat().st_mode & 0o777)
                os.replace(tmp_name, path)
            else:
                os.unlink(tmp_name)
                rewritten -= 1
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    return rewritten, backups


def table_info(con: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"]: row for row in rows}


def fallback_for_column(info: sqlite3.Row) -> Any:
    col_type = (info["type"] or "").upper()
    if "INT" in col_type or "REAL" in col_type or "NUM" in col_type:
        return 0
    return ""


def values_for_rollout(rollout: Rollout, provider: str | None, adopt_provider: bool) -> dict[str, Any]:
    model_provider = provider if adopt_provider and provider else rollout.model_provider
    return {
        "id": rollout.id,
        "rollout_path": str(rollout.path),
        "created_at": rollout.created_at_ms // 1000,
        "updated_at": rollout.updated_at_ms // 1000,
        "source": rollout.source,
        "model_provider": model_provider,
        "cwd": rollout.cwd,
        "title": rollout.title,
        "sandbox_policy": rollout.sandbox_policy,
        "approval_mode": rollout.approval_mode,
        "tokens_used": 0,
        "has_user_event": rollout.has_user_event,
        "archived": 0,
        "archived_at": None,
        "git_sha": None,
        "git_branch": None,
        "git_origin_url": None,
        "cli_version": rollout.cli_version,
        "first_user_message": rollout.first_user_message,
        "agent_nickname": None,
        "agent_role": None,
        "memory_mode": "enabled",
        "model": rollout.model,
        "reasoning_effort": rollout.reasoning_effort,
        "agent_path": None,
        "created_at_ms": rollout.created_at_ms,
        "updated_at_ms": rollout.updated_at_ms,
        "thread_source": rollout.thread_source,
        "preview": rollout.preview,
    }


def repair_sqlite(
    codex_home: pathlib.Path,
    rollouts: dict[str, Rollout],
    provider: str | None,
    adopt_provider: bool,
    dry_run: bool,
) -> dict[str, int]:
    db_path = codex_home / "state_5.sqlite"
    stats = {"sqlite_threads": 0, "sqlite_inserted": 0, "sqlite_updated": 0, "provider_adopted": 0}
    if not db_path.exists():
        return stats

    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    try:
        cols = table_info(con, "threads")
        if not cols:
            return stats

        existing_rows = con.execute("SELECT * FROM threads").fetchall()
        existing = {row["id"]: row for row in existing_rows}
        stats["sqlite_threads"] = len(existing)

        if dry_run:
            if adopt_provider and provider:
                stats["provider_adopted"] = sum(
                    1 for row in existing_rows if (row["model_provider"] or "") != provider
                )
            stats["sqlite_inserted"] = sum(1 for tid in rollouts if tid not in existing)
            for tid, rollout in rollouts.items():
                row = existing.get(tid)
                if row and rollout.updated_at_ms > (row["updated_at_ms"] or row["updated_at"] * 1000):
                    stats["sqlite_updated"] += 1
            return stats

        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")

        if adopt_provider and provider and "model_provider" in cols:
            cur.execute(
                "UPDATE threads SET model_provider=? WHERE COALESCE(model_provider, '') <> ?",
                (provider, provider),
            )
            stats["provider_adopted"] = cur.rowcount if cur.rowcount >= 0 else 0

        for tid, rollout in rollouts.items():
            values = values_for_rollout(rollout, provider, adopt_provider)
            row = existing.get(tid)
            if row is None:
                insert_values: dict[str, Any] = {}
                for name, info in cols.items():
                    if name in values:
                        insert_values[name] = values[name]
                    elif info["notnull"] and info["dflt_value"] is None:
                        insert_values[name] = fallback_for_column(info)
                names = list(insert_values)
                placeholders = ",".join("?" for _ in names)
                cur.execute(
                    f"INSERT INTO threads ({','.join(names)}) VALUES ({placeholders})",
                    [insert_values[name] for name in names],
                )
                stats["sqlite_inserted"] += 1
                continue

            updates: dict[str, Any] = {}
            for name in ("rollout_path", "source", "cwd", "cli_version", "thread_source"):
                if name in cols and values.get(name) and not row[name]:
                    updates[name] = values[name]
            for name in ("title", "first_user_message", "preview", "sandbox_policy", "approval_mode"):
                if name in cols and values.get(name) and not row[name]:
                    updates[name] = values[name]
            if "created_at_ms" in cols and values["created_at_ms"] and not row["created_at_ms"]:
                updates["created_at_ms"] = values["created_at_ms"]
            if "created_at" in cols and values["created_at"] and not row["created_at"]:
                updates["created_at"] = values["created_at"]
            if "updated_at_ms" in cols:
                row_updated_ms = row["updated_at_ms"] or (row["updated_at"] or 0) * 1000
                if values["updated_at_ms"] > row_updated_ms:
                    updates["updated_at_ms"] = values["updated_at_ms"]
                    if "updated_at" in cols:
                        updates["updated_at"] = values["updated_at"]
            if "has_user_event" in cols and values["has_user_event"] and not row["has_user_event"]:
                updates["has_user_event"] = values["has_user_event"]

            if updates:
                assignments = ", ".join(f"{name}=?" for name in updates)
                cur.execute(
                    f"UPDATE threads SET {assignments} WHERE id=?",
                    [*updates.values(), tid],
                )
                stats["sqlite_updated"] += 1

        con.commit()
        stats["sqlite_threads"] = con.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return stats


def load_thread_rows(codex_home: pathlib.Path) -> list[sqlite3.Row]:
    db_path = codex_home / "state_5.sqlite"
    if not db_path.exists():
        return []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cols = table_info(con, "threads")
        if not cols:
            return []
        return con.execute("SELECT * FROM threads WHERE COALESCE(archived, 0) = 0").fetchall()
    finally:
        con.close()


def write_session_index(
    codex_home: pathlib.Path,
    rollouts: dict[str, Rollout],
    dry_run: bool,
) -> int:
    index_path = codex_home / "session_index.jsonl"
    rows = load_thread_rows(codex_home)
    index_items: dict[str, dict[str, Any]] = {}

    for row in rows:
        path = row["rollout_path"]
        if not path:
            continue
        rollout = rollouts.get(row["id"])
        path_exists = pathlib.Path(path).exists()
        if rollout is None and not path_exists:
            continue
        updated_ms = row["updated_at_ms"] or (row["updated_at"] or 0) * 1000
        if rollout and rollout.updated_at_ms > updated_ms:
            updated_ms = rollout.updated_at_ms
        title = row["title"] or row["first_user_message"] or (rollout.title if rollout else row["id"])
        index_items[row["id"]] = {
            "id": row["id"],
            "thread_name": one_line(title, limit=220),
            "updated_at": iso_from_ms(int(updated_ms)),
            "_sort": int(updated_ms),
        }

    for tid, rollout in rollouts.items():
        index_items.setdefault(
            tid,
            {
                "id": tid,
                "thread_name": one_line(rollout.title, limit=220),
                "updated_at": iso_from_ms(rollout.updated_at_ms),
                "_sort": rollout.updated_at_ms,
            },
        )

    ordered = sorted(index_items.values(), key=lambda item: (item["_sort"], item["id"]))
    if dry_run:
        return len(ordered)

    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".session_index.", suffix=".jsonl", dir=index_path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for item in ordered:
            item = dict(item)
            item.pop("_sort", None)
            fh.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.chmod(tmp_name, 0o600)
    os.replace(tmp_name, index_path)
    return len(ordered)


def provider_counts(codex_home: pathlib.Path) -> dict[str, int]:
    db_path = codex_home / "state_5.sqlite"
    if not db_path.exists():
        return {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT COALESCE(model_provider, '') AS provider, COUNT(*) FROM threads GROUP BY provider"
        ).fetchall()
        return {provider or "(empty)": count for provider, count in rows}
    finally:
        con.close()


def latest_resumable_rollout(
    rollouts: dict[str, Rollout],
    cwd: str | None = None,
    since_ms: int | None = None,
) -> Rollout | None:
    wanted_cwd = os.path.abspath(os.path.expanduser(cwd)) if cwd else None
    candidates: list[Rollout] = []
    for rollout in rollouts.values():
        if not rollout.has_user_event:
            continue
        if since_ms is not None and rollout.updated_at_ms < since_ms and rollout.created_at_ms < since_ms:
            continue
        if wanted_cwd:
            rollout_cwd = os.path.abspath(os.path.expanduser(rollout.cwd)) if rollout.cwd else ""
            if rollout_cwd != wanted_cwd:
                continue
        candidates.append(rollout)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.updated_at_ms, item.created_at_ms, item.id))


def count_index(codex_home: pathlib.Path) -> int:
    path = codex_home / "session_index.jsonl"
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if line.strip())


def cmd_repair(args: argparse.Namespace) -> int:
    codex_home = pathlib.Path(args.codex_home).expanduser()
    provider = resolve_provider(args)
    adopt_provider = not args.no_adopt_provider
    rollouts = collect_rollouts(codex_home)

    backups: list[pathlib.Path] = []
    rollout_backups: list[pathlib.Path] = []
    if not args.dry_run and not args.no_backup:
        backup_dir = pathlib.Path(args.backup_dir).expanduser() if args.backup_dir else None
        backups = backup_state(codex_home, backup_dir)
        rollout_backup_dir = (
            (backup_dir or (codex_home / "backups" / "cxsw-sessions"))
            / f"rollouts.{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        )
    else:
        rollout_backup_dir = None

    rollout_rewritten = 0
    if adopt_provider and provider and not args.no_rewrite_rollouts:
        rollout_rewritten, rollout_backups = rewrite_rollout_providers(
            rollouts,
            provider,
            codex_home,
            rollout_backup_dir,
            args.dry_run,
        )
        if rollout_rewritten and not args.dry_run:
            rollouts = collect_rollouts(codex_home)

    stats = repair_sqlite(codex_home, rollouts, provider, adopt_provider, args.dry_run)
    index_entries = write_session_index(codex_home, rollouts, args.dry_run)

    mode = "dry-run " if args.dry_run else ""
    provider_label = provider or "(preserve)"
    print(
        f"Session repair {mode}OK: provider={provider_label} "
        f"rollouts={len(rollouts)} sqlite_threads={stats['sqlite_threads']} "
        f"inserted={stats['sqlite_inserted']} updated={stats['sqlite_updated']} "
        f"provider_adopted={stats['provider_adopted']} "
        f"rollout_provider_rewritten={rollout_rewritten} index_entries={index_entries}"
    )
    for backup in backups:
        print(f"Backup: {backup}")
    if rollout_backups:
        print(f"Backup: {rollout_backup_dir} ({len(rollout_backups)} rollout files)")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    codex_home = pathlib.Path(args.codex_home).expanduser()
    rollouts = collect_rollouts(codex_home)
    counts = provider_counts(codex_home)
    index_n = count_index(codex_home)
    if counts:
        providers = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
    else:
        providers = "none"
    print(f"Sessions: rollouts={len(rollouts)} index_entries={index_n} providers=[{providers}]")
    return 0


def cmd_latest(args: argparse.Namespace) -> int:
    codex_home = pathlib.Path(args.codex_home).expanduser()
    rollouts = collect_rollouts(codex_home)
    latest = latest_resumable_rollout(rollouts, cwd=args.cwd, since_ms=args.since_ms)
    if latest is None and args.cwd and not args.strict_cwd:
        latest = latest_resumable_rollout(rollouts, since_ms=args.since_ms)
    if latest is None and args.since_ms is not None and not args.strict_since:
        latest = latest_resumable_rollout(rollouts, cwd=args.cwd)
    if latest is None:
        print("No resumable Codex session found.", file=sys.stderr)
        return 1
    if args.id_only:
        print(latest.id)
    else:
        print(f"codex resume {latest.id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    repair = sub.add_parser("repair", help="Rebuild session index and adopt threads to a provider")
    repair.add_argument("--codex-home", default=os.path.expanduser("~/.codex"))
    repair.add_argument("--mode", choices=sorted(PROVIDER_BY_MODE))
    repair.add_argument("--provider", help="Provider id to write into state_5.sqlite threads")
    repair.add_argument("--no-adopt-provider", action="store_true", help="Preserve existing provider tags")
    repair.add_argument("--dry-run", action="store_true")
    repair.add_argument("--no-backup", action="store_true")
    repair.add_argument("--no-rewrite-rollouts", action="store_true")
    repair.add_argument("--backup-dir")
    repair.set_defaults(func=cmd_repair)

    status = sub.add_parser("status", help="Print local session metadata counts")
    status.add_argument("--codex-home", default=os.path.expanduser("~/.codex"))
    status.set_defaults(func=cmd_status)

    latest = sub.add_parser("latest", help="Print the latest resumable Codex command")
    latest.add_argument("--codex-home", default=os.path.expanduser("~/.codex"))
    latest.add_argument("--cwd", help="Prefer sessions from this working directory")
    latest.add_argument("--since-ms", type=int, help="Prefer sessions created/updated after this epoch millis")
    latest.add_argument("--strict-cwd", action="store_true", help="Do not fall back to another cwd")
    latest.add_argument("--strict-since", action="store_true", help="Do not fall back before --since-ms")
    latest.add_argument("--id-only", action="store_true")
    latest.set_defaults(func=cmd_latest)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
