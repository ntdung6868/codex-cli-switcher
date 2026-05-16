#!/usr/bin/env python3
"""Temporarily disable app-backed Codex plugins while cxsw proxy mode is active.

Codex model proxying can work while ~/.codex/auth.json is stale, but app-backed
plugins/connectors still start through Codex's native OAuth path. If that native
refresh token has been revoked, MCP startup can fail before the proxied model
request is useful. This helper disables non-bundled plugins in proxy modes and
restores only the plugins it changed when returning to native mode.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timezone


PLUGIN_HEADER_RE = re.compile(r'^\s*\[plugins\."([^"]+)"\]\s*(?:#.*)?$')
ANY_HEADER_RE = re.compile(r"^\s*\[[^\]]+\]\s*(?:#.*)?$")
ENABLED_RE = re.compile(r"^(\s*enabled\s*=\s*)(true|false)(\s*(?:#.*)?)(\r?\n?)$")
DEFAULT_ALLOW_RE = r"@openai-bundled$"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_state(path: pathlib.Path) -> set[str]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return set()
    except Exception:
        return set()
    plugins = data.get("disabled_plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        return set()
    return {p for p in plugins if isinstance(p, str) and p}


def write_state(path: pathlib.Path, plugins: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "updated_at": utc_now(),
        "disabled_plugins": sorted(plugins),
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)


def remove_state(path: pathlib.Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def write_config(path: pathlib.Path, text: str) -> None:
    mode = 0o600
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        pass
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.chmod(mode)
    tmp.replace(path)


def plugin_sections(lines: list[str]) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    i = 0
    while i < len(lines):
        m = PLUGIN_HEADER_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        start = i
        i += 1
        while i < len(lines) and not ANY_HEADER_RE.match(lines[i]):
            i += 1
        out.append((name, start, i))
    return out


def enabled_value(lines: list[str], start: int, end: int) -> tuple[int, bool] | None:
    for idx in range(start + 1, end):
        m = ENABLED_RE.match(lines[idx])
        if m:
            return idx, m.group(2) == "true"
    return None


def allow_pattern() -> re.Pattern[str]:
    pattern = os.environ.get("CXSW_PROXY_PLUGIN_ALLOW_RE", DEFAULT_ALLOW_RE)
    try:
        return re.compile(pattern)
    except re.error as exc:
        sys.exit(f"invalid CXSW_PROXY_PLUGIN_ALLOW_RE: {exc}")


def should_guard_plugin(name: str, allow_re: re.Pattern[str]) -> bool:
    extra_allow = {
        p.strip()
        for p in os.environ.get("CXSW_PROXY_PLUGIN_ALLOW", "").split(",")
        if p.strip()
    }
    if name in extra_allow:
        return False
    return not allow_re.search(name)


def set_enabled_line(line: str, value: bool) -> str:
    m = ENABLED_RE.match(line)
    if not m:
        return line
    return f"{m.group(1)}{'true' if value else 'false'}{m.group(3)}{m.group(4)}"


def guard(config: pathlib.Path, state: pathlib.Path) -> int:
    original = config.read_text()
    lines = original.splitlines(keepends=True)
    allow_re = allow_pattern()
    state_plugins = read_state(state)
    disabled_now: list[str] = []

    for name, start, end in plugin_sections(lines):
        if not should_guard_plugin(name, allow_re):
            continue
        enabled = enabled_value(lines, start, end)
        if not enabled:
            continue
        idx, is_enabled = enabled
        if is_enabled:
            lines[idx] = set_enabled_line(lines[idx], False)
            disabled_now.append(name)
            state_plugins.add(name)

    text = "".join(lines)
    if text != original:
        write_config(config, text)
    if state_plugins:
        write_state(state, state_plugins)

    if disabled_now:
        print(f"Proxy plugin guard: disabled {len(disabled_now)} plugin(s): {', '.join(disabled_now)}")
    elif state_plugins:
        print(f"Proxy plugin guard: already active for {len(state_plugins)} plugin(s).")
    else:
        print("Proxy plugin guard: no non-bundled enabled plugins to disable.")
    return 0


def restore(config: pathlib.Path, state: pathlib.Path) -> int:
    state_plugins = read_state(state)
    if not state_plugins:
        print("Proxy plugin guard: nothing to restore.")
        return 0

    original = config.read_text()
    lines = original.splitlines(keepends=True)
    restored: list[str] = []
    seen: set[str] = set()

    for name, start, end in plugin_sections(lines):
        if name not in state_plugins:
            continue
        seen.add(name)
        enabled = enabled_value(lines, start, end)
        if not enabled:
            continue
        idx, is_enabled = enabled
        if not is_enabled:
            lines[idx] = set_enabled_line(lines[idx], True)
            restored.append(name)

    text = "".join(lines)
    if text != original:
        write_config(config, text)
    remove_state(state)

    missing = sorted(state_plugins - seen)
    detail = f"; missing from config: {', '.join(missing)}" if missing else ""
    print(f"Proxy plugin guard: restored {len(restored)} plugin(s){detail}.")
    return 0


def status(config: pathlib.Path, state: pathlib.Path) -> int:
    text = config.read_text()
    lines = text.splitlines(keepends=True)
    allow_re = allow_pattern()
    state_plugins = read_state(state)
    guarded_enabled: list[str] = []
    guarded_disabled: list[str] = []

    for name, start, end in plugin_sections(lines):
        if not should_guard_plugin(name, allow_re):
            continue
        enabled = enabled_value(lines, start, end)
        if not enabled:
            continue
        _, is_enabled = enabled
        if is_enabled:
            guarded_enabled.append(name)
        elif name in state_plugins:
            guarded_disabled.append(name)

    print(f"Proxy plugin guard: {'active' if state_plugins else 'inactive'}")
    print(f"  state plugins: {len(state_plugins)}")
    if guarded_disabled:
        print(f"  disabled by guard: {', '.join(sorted(guarded_disabled))}")
    if guarded_enabled:
        print(f"  enabled non-bundled plugins: {', '.join(sorted(guarded_enabled))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["guard", "restore", "status"])
    ap.add_argument("--config", required=True)
    ap.add_argument("--state", required=True)
    args = ap.parse_args()

    config = pathlib.Path(args.config).expanduser()
    state = pathlib.Path(args.state).expanduser()
    if not config.exists():
        sys.exit(f"config not found: {config}")

    if args.action == "guard":
        return guard(config, state)
    if args.action == "restore":
        return restore(config, state)
    return status(config, state)


if __name__ == "__main__":
    raise SystemExit(main())
