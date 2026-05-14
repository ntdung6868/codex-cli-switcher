#!/usr/bin/env python3
"""Diagnose Codex.app plugin/marketplace mismatches.

The Codex.app Electron renderer treats a "configured non-curated plugin no
longer exists in discovered marketplaces during cache refresh" warning as a
fatal error and renders the crash UI. This breaks our hot-reload flow even
when the new app-server is healthy.

Root cause: ~/.codex/config.toml lists `[plugins."NAME@MARKETPLACE"]` entries
whose `NAME` is not present in the marketplace's discovered plugin list at
boot time.

This script scans the config, locates each marketplace's cache, walks the
plugin manifest, and reports any orphaned entries. Optionally rewrites the
config to comment them out (preserving the rest of the file).
"""
from __future__ import annotations
import argparse, json, pathlib, re, sys, datetime, shutil

PLUGIN_LINE_RE = re.compile(r'^\s*\[plugins\."([^"@]+)@([^"]+)"\]\s*$')
MARKETPLACE_LINE_RE = re.compile(r'^\s*\[marketplaces\.([A-Za-z0-9._-]+)\]\s*$')
SOURCE_LINE_RE = re.compile(r'^\s*source\s*=\s*"([^"]+)"\s*$')
SOURCE_TYPE_LINE_RE = re.compile(r'^\s*source_type\s*=\s*"([^"]+)"\s*$')

def parse_config(text: str):
    """Return (plugins=[(name,marketplace)], marketplaces={name:{type,source}})."""
    plugins, marketplaces = [], {}
    current_mp = None
    for line in text.splitlines():
        if m := PLUGIN_LINE_RE.match(line):
            plugins.append((m.group(1), m.group(2)))
            current_mp = None
            continue
        if m := MARKETPLACE_LINE_RE.match(line):
            current_mp = m.group(1)
            marketplaces.setdefault(current_mp, {})
            continue
        if current_mp:
            if m := SOURCE_LINE_RE.match(line):
                marketplaces[current_mp]["source"] = m.group(1)
            elif m := SOURCE_TYPE_LINE_RE.match(line):
                marketplaces[current_mp]["source_type"] = m.group(1)
    return plugins, marketplaces

def discover_plugins(marketplace_name: str, info: dict, home: pathlib.Path) -> set[str] | None:
    """Return the set of plugin names this marketplace provides, or None if it can't be probed."""
    source = info.get("source", "")
    if not source:
        return None
    # `source` may be a local path (source_type=local) or git URL (source_type=git).
    if info.get("source_type") == "git":
        # Look for cached clone under known paths
        for base in (
            home / ".codex" / "plugins" / "cache" / marketplace_name,
            home / ".codex" / ".tmp" / "marketplaces" / marketplace_name,
        ):
            if base.exists():
                return _plugins_in_dir(base)
        return None
    # source_type=local (or unset → assume path)
    base = pathlib.Path(source).expanduser()
    if not base.exists():
        return None
    return _plugins_in_dir(base)

def _plugins_in_dir(base: pathlib.Path) -> set[str] | None:
    # Try marketplace.json first (authoritative)
    manifest_paths = list(base.rglob(".agents/plugins/marketplace.json")) + list(base.rglob("marketplace.json"))
    for mp in manifest_paths:
        try:
            data = json.loads(mp.read_text())
            if isinstance(data, dict) and isinstance(data.get("plugins"), list):
                return {p["name"] for p in data["plugins"] if isinstance(p, dict) and "name" in p}
        except Exception:
            continue
    # Fall back to directories under plugins/
    plugins_dir = base / "plugins"
    if plugins_dir.is_dir():
        return {p.name for p in plugins_dir.iterdir() if p.is_dir() and not p.name.startswith(".")}
    return None

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--fix", action="store_true", help="Comment out orphaned plugin entries")
    ap.add_argument("--disable", action="append", default=[],
                    help='Force-disable a plugin entry by "name@marketplace" (repeatable). '
                         'Useful when Codex.app upstream emits false-positive missing-plugin warnings.')
    args, _unknown = ap.parse_known_args()

    config = pathlib.Path(args.config)
    if not config.exists():
        print(f"config not found: {config}", file=sys.stderr)
        return 1

    text = config.read_text()
    plugins, marketplaces = parse_config(text)
    home = pathlib.Path.home()

    print(f"Config: {config}")
    print(f"  → {len(plugins)} plugin entries, {len(marketplaces)} marketplaces\n")

    # Resolve which plugins each marketplace provides
    mp_plugins = {}
    for name, info in marketplaces.items():
        plugs = discover_plugins(name, info, home)
        mp_plugins[name] = plugs
        if plugs is None:
            print(f"  marketplace '{name}'  source={info.get('source','?')}  → CANNOT PROBE (cache missing)")
        else:
            print(f"  marketplace '{name}'  → {len(plugs)} plugins available")
    print()

    # Cross-check
      # Parse --disable arguments: "name@marketplace"
    forced_disable = set()
    for spec in args.disable:
        if "@" not in spec:
            print(f"  bad --disable spec '{spec}' (need NAME@MARKETPLACE)", file=sys.stderr)
            continue
        n, m = spec.split("@", 1)
        forced_disable.add((n.strip(), m.strip()))

    orphans = []
    for plugin_name, mp_name in plugins:
        key = (plugin_name, mp_name)
        plugs = mp_plugins.get(mp_name)
        if key in forced_disable:
            status = "FORCED"
            orphans.append(key)
        elif plugs is None:
            status = "?"  # cannot verify
        elif plugin_name in plugs:
            status = "OK"
        else:
            status = "MISSING"
            orphans.append(key)
        print(f"  [{status:7s}] plugins.\"{plugin_name}@{mp_name}\"")

    print()
    if not orphans:
        print("✓ No orphaned plugins detected.")
        return 0

    print(f"✗ {len(orphans)} orphaned plugin(s) found.")
    print()
    print("These entries reference plugins that are NOT in the discovered marketplace.")
    print("Codex.app's renderer treats this as a fatal error and shows the crash overlay")
    print("on every restart of the app-server child — which breaks `cxsw use <mode>`'s")
    print("hot reload, even though the new backend is healthy.")
    print()

    if not args.fix:
        print("Run `cxsw doctor --fix` to comment out these entries (a backup is written).")
        return 1

    # Comment out orphan entries (and their immediate following key/value lines until the next [section])
    backup = config.with_suffix(config.suffix + f".bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(config, backup)
    print(f"Backup: {backup}")

    lines = text.splitlines(keepends=True)
    orphan_keys = {(n, m) for n, m in orphans}
    out, in_orphan = [], False
    for line in lines:
        if m := PLUGIN_LINE_RE.match(line):
            if (m.group(1), m.group(2)) in orphan_keys:
                in_orphan = True
                out.append(f"# cxsw doctor disabled (plugin missing from marketplace) {line}")
                continue
            in_orphan = False
            out.append(line)
            continue
        if line.lstrip().startswith("[") and in_orphan:
            in_orphan = False
        if in_orphan:
            out.append("# " + line if not line.startswith("#") else line)
        else:
            out.append(line)

    config.write_text("".join(out))
    config.chmod(0o600)
    print(f"✓ Disabled {len(orphans)} plugin entries. Codex.app will pick up the change on next app-server respawn.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
