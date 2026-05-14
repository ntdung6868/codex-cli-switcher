#!/usr/bin/env python3
"""Mutate ~/.codex/config.toml so Codex CLI talks to a chosen backend.

Modes:
  - cliproxy : route via CLIProxyAPI  (model_provider=cliproxy)
  - 9router  : route via 9Router      (model_provider=r9router, dot-name safe)
  - native   : strip our managed lines, leave everything else intact

Only marker-fenced regions are touched. Everything else (plugins, projects,
marketplaces, comments) is preserved.
"""
from __future__ import annotations
import argparse, pathlib, re, sys

MARKER_TOP_BEGIN  = "# === cxsw managed: provider key ==="
MARKER_TOP_END    = "# === cxsw managed: provider key end ==="
MARKER_TBL_BEGIN  = "# === cxsw managed: provider block ==="
MARKER_TBL_END    = "# === cxsw managed: provider block end ==="

# 9router has TOML-safe bare key
PROVIDERS = {
    "cliproxy": dict(
        id="cliproxy",
        name="CLIProxyAPI",
        env_key="CLIPROXY_API_KEY",
        wire_api="responses",
        default_url="http://127.0.0.1:8317/v1",
    ),
    "9router": dict(
        id="r9router",
        name="9Router",
        env_key="NINEROUTER_API_KEY",
        wire_api="responses",
        default_url="http://127.0.0.1:20128/v1",
    ),
}

def strip_managed(text: str) -> str:
    """Remove both marker-fenced blocks if present, plus any orphan lines we own."""
    out = text
    for begin, end in [(MARKER_TOP_BEGIN, MARKER_TOP_END), (MARKER_TBL_BEGIN, MARKER_TBL_END)]:
        out = re.sub(
            rf"\n?{re.escape(begin)}.*?{re.escape(end)}\n?",
            "\n",
            out,
            flags=re.DOTALL,
        )
    # Remove our managed top-level model_provider line if it leaked out
    out = re.sub(r"(?m)^\s*model_provider\s*=\s*\"(cliproxy|r9router)\"\s*\n", "", out)
    # Remove our managed [model_providers.cliproxy] / [model_providers.r9router] blocks
    # if they exist outside the markers.
    out = re.sub(
        r"(?ms)^\[model_providers\.(?:cliproxy|r9router)\][^\[]*",
        "",
        out,
    )
    # Collapse triple-blank-lines we may have introduced.
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out

def insert_top_level(text: str, payload: str) -> str:
    """Insert payload before the first '[section]' header, or prepend if none."""
    m = re.search(r"^\[", text, flags=re.M)
    if not m:
        return payload + ("\n" if not text.startswith("\n") else "") + text
    idx = m.start()
    return text[:idx] + payload + text[idx:]

def build_top(provider_id: str) -> str:
    return (
        f"\n{MARKER_TOP_BEGIN}\n"
        f"model_provider = \"{provider_id}\"\n"
        f"{MARKER_TOP_END}\n"
    )

def build_table(p: dict, base_url: str) -> str:
    return (
        f"\n{MARKER_TBL_BEGIN}\n"
        f"[model_providers.{p['id']}]\n"
        f"name = \"{p['name']}\"\n"
        f"base_url = \"{base_url}\"\n"
        f"wire_api = \"{p['wire_api']}\"\n"
        f"env_key = \"{p['env_key']}\"\n"
        f"{MARKER_TBL_END}\n"
    )

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["cliproxy", "9router", "native"])
    ap.add_argument("config_path")
    ap.add_argument("--cliproxy-url", default=PROVIDERS["cliproxy"]["default_url"])
    ap.add_argument("--r9router-url", default=PROVIDERS["9router"]["default_url"])
    args = ap.parse_args()

    p = pathlib.Path(args.config_path)
    if not p.exists():
        sys.exit(f"config not found: {p}")
    original = p.read_text()
    text = strip_managed(original)

    if args.mode != "native":
        provider = PROVIDERS[args.mode]
        url = args.cliproxy_url if args.mode == "cliproxy" else args.r9router_url
        text = insert_top_level(text, build_top(provider["id"]))
        if not text.endswith("\n"):
            text += "\n"
        text += build_table(provider, url)

    # Idempotent: if no change, do not write.
    if text != original:
        # Atomic write
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text)
        tmp.chmod(0o600)
        tmp.replace(p)
    print(f"Applied mode={args.mode} to {p}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
