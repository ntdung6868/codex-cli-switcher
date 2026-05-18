# codex-cli-switcher

`codex-cli-switcher` is a macOS command-line switcher for routing the OpenAI Codex CLI
between native ChatGPT, CLIProxyAPI, and 9Router backends.

It edits only its own marker-fenced blocks in `~/.codex/config.toml`, keeps the
rest of your Codex configuration intact, and stores local state under your user
profile.

```text
╭───────────────────────────────────────────────────────────────╮
│  cxsw — Codex Backend Switcher                                │
├───────────────────────────────────────────────────────────────┤
│  Mode:    cliproxy                                            │
│  Status:  CLIProxyAPI (http://127.0.0.1:8317/v1) HTTP 200      │
│  codex:   codex-cli 0.130.0                                   │
╰───────────────────────────────────────────────────────────────╯
```

## Features

- Switch Codex CLI between `native`, `cliproxy`, and `9router` modes.
- Preserve existing Codex projects, plugins, marketplaces, model settings, and comments.
- Probe backend health from the CLI or interactive menu.
- Relaunch, quit, or hot-reload Codex.app after changing backends.
- Diagnose plugin/marketplace mismatches that can trigger Codex.app crash overlays.
- Verify that the plain `codex` command still points to the official
  `@openai/codex` CLI and has not been replaced by `cxsw`.
- Disable app-backed plugins while proxy mode is active so `codex_apps` does not
  fail on a stale native `~/.codex/auth.json` OAuth token.
- Restore Codex OAuth account JSON files into CLIProxyAPI. 9Router Codex OAuth
  imports stay behind an explicit unsafe opt-in to avoid double refreshers.
- Repair Codex local session indexes so old threads stay visible after switching backends.
- Package as a single npm-installed `cxsw` command with no runtime npm dependencies.

## Requirements

- macOS.
- OpenAI Codex CLI already initialized at least once.
- `zsh`, `python3`, `curl`, and `sqlite3` available on `PATH`.
- Optional: Codex.app at `/Applications/Codex.app` for app relaunch helpers.
- Optional: CLIProxyAPI on `http://127.0.0.1:8317/v1`.
- Optional: 9Router on `http://127.0.0.1:20128/v1`.

## Installation

```bash
npm install -g codex-cli-switcher
cxsw init
```

Then open the menu:

```bash
cxsw
```

You can also run directly from a cloned repository:

```bash
git clone https://github.com/ntdung6868/codex-cli-switcher.git
cd codex-cli-switcher
./cxsw
```

## Quick Start

```bash
cxsw status
cxsw use cliproxy
cxsw use 9router
cxsw use native
```

By default, `cxsw use <mode>` refuses unsafe switches while Codex.app or an
interactive `codex` session is still running. This prevents a resumed thread
from keeping stale backend/auth state after you switch. Use one of the reload
forms for app sessions:

```bash
cxsw use --relaunch cliproxy
cxsw relaunch-app
cxsw quit-app
```

If you intentionally want the old "rewrite config only" behavior, add
`--allow-live-sessions`.

Advanced hot reload is also available:

```bash
cxsw use --hot-reload cliproxy
cxsw hot-reload
```

Hot reload kills only the Codex.app `app-server` child process and lets Electron
spawn a fresh one. It is faster, but a broken plugin configuration can still
surface Codex.app's crash overlay. Use `cxsw doctor` before relying on it.

## Modes

| Mode | Backend | Default target |
| --- | --- | --- |
| `native` | OpenAI direct | `~/.codex/auth.json` |
| `cliproxy` | CLIProxyAPI | `http://127.0.0.1:8317/v1` |
| `9router` | 9Router | `http://127.0.0.1:20128/v1` |

For `9router`, the TOML provider id is stored as `r9router` because TOML bare
keys cannot start with a digit.

## Commands

```bash
cxsw                         # interactive menu
cxsw init                    # create local state and native snapshots
cxsw status                  # active mode, health checks, account counts
cxsw codex-status            # verify plain "codex" is still official Codex CLI
cxsw current                 # print only the active mode
cxsw last-resume             # print latest "codex resume <id>" fallback

cxsw use cliproxy            # switch to CLIProxyAPI
cxsw use 9router             # switch to 9Router
cxsw use native              # remove managed proxy blocks
cxsw use --relaunch native   # switch and relaunch Codex.app
cxsw use --quit-app native   # switch and quit Codex.app
cxsw use --hot-reload native # switch and restart app-server child only

cxsw relaunch-app            # quit and reopen Codex.app
cxsw quit-app                # quit Codex.app without reopening
cxsw hot-reload              # advanced app-server reload

cxsw doctor                  # inspect plugin/marketplace mismatches
cxsw doctor --fix            # comment out orphaned plugin entries
cxsw plugin-guard status     # show proxy-mode plugin guard state

cxsw import-backup-cliproxy  # backup OAuth JSON files to CLIProxyAPI dir
cxsw import-backup-9router   # unsafe opt-in: backup OAuth files to 9Router SQLite
cxsw sync-cliproxy-9router   # unsafe opt-in: CLIProxyAPI auth dir to 9Router SQLite
cxsw repair-sessions         # rebuild session index + adopt threads to active backend
cxsw repair-sessions --dry-run
```

## Configuration

| Environment variable | Default |
| --- | --- |
| `CXSW_STATE_DIR` | `${XDG_STATE_HOME:-$HOME/.local/state}/cxsw` |
| `CODEX_SWITCHER_DIR` | legacy alias for `CXSW_STATE_DIR` |
| `CODEX_HOME` | `$HOME/.codex` |
| `CLIPROXY_AUTH_DIR` | `$HOME/.cli-proxy-api` |
| `CLIPROXY_BASE_URL` | `http://127.0.0.1:8317/v1` |
| `CLIPROXY_API_KEY` | optional override; default bearer token is `your-api-key-1` |
| `NINEROUTER_DB` | `$HOME/.9router/db/data.sqlite` |
| `NINEROUTER_BASE_URL` | `http://127.0.0.1:20128/v1` |
| `NINEROUTER_API_KEY` | optional override; default bearer token is `sk_9router` |
| `CLIPROXY_BACKUP_DIR` | `$HOME/Documents/Backups/codex-oauth-backup/cli-proxy-api-auth` |
| `CXSW_SESSION_SYNC` | `1`; set `0` to skip automatic session repair on switch |
| `CXSW_PROXY_PLUGIN_GUARD` | `1`; set `0` to keep non-bundled plugins enabled in proxy mode |
| `CXSW_LIVE_SESSION_GUARD` | `1`; set `0` to allow switching while Codex.app/codex sessions are live |
| `PYTHON_BIN` | `python3` |
| `CODEX_APP_PATH` | `/Applications/Codex.app` |

## What cxsw Writes

When you switch to a proxy backend, `cxsw` inserts two managed regions into
`~/.codex/config.toml`:

```toml
# === cxsw managed: provider key ===
model_provider = "cliproxy"
# === cxsw managed: provider key end ===

# === cxsw managed: provider block ===
[model_providers.cliproxy]
name = "CLIProxyAPI"
base_url = "http://127.0.0.1:8317/v1"
wire_api = "responses"

[model_providers.cliproxy.auth]
command = "/bin/sh"
args = ["-c", "if [ -n \"${CLIPROXY_API_KEY:-}\" ]; then printf %s \"${CLIPROXY_API_KEY}\"; else printf %s \"$1\"; fi", "cxsw-auth", "your-api-key-1"]
# === cxsw managed: provider block end ===
```

The auth command means `codex` works even when the shell does not export the
proxy API key. If you do export `CLIPROXY_API_KEY` or `NINEROUTER_API_KEY`,
that value takes precedence over the local default.

Switching back to `native` removes only those managed regions. Your other Codex
settings are left unchanged.

## Codex CLI Command Safety

`cxsw` does not replace, alias, wrap, or patch the official `codex` command.
Plain `codex` should remain the npm-installed `@openai/codex` CLI, while `cxsw`
stays a separate backend switcher command.

Check that setup with:

```bash
cxsw codex-status
```

## Proxy Plugin Guard

Codex can route model calls through `cliproxy` or `9router` while the native
`~/.codex/auth.json` token is stale. App-backed plugins such as GitHub and
Vercel still start through Codex's native OAuth path, though, and can fail MCP
startup with `token_revoked`.

When `CXSW_PROXY_PLUGIN_GUARD=1`, switching to `cliproxy` or `9router`
temporarily disables enabled non-bundled plugins and records exactly which ones
it changed under `~/.local/state/cxsw/proxy-plugin-guard.json`. Switching back
to `native` restores only that recorded set. Bundled local plugins such as
`browser@openai-bundled` are left alone.

## Session Repair

Codex stores raw conversations in `~/.codex/sessions/`, but its visible thread
list is also indexed in `~/.codex/state_5.sqlite` and
`~/.codex/session_index.jsonl`. When switching between `native`, `cliproxy`,
and `9router`, older threads can stay tagged with the previous provider and
disappear from provider-filtered views.

By default, `cxsw use <mode>` runs session repair after the backend switch. It:

- backs up `state_5.sqlite` and `session_index.jsonl` under
  `~/.codex/backups/cxsw-sessions/`;
- scans every rollout in `~/.codex/sessions/**/*.jsonl`;
- rewrites only the `session_meta.payload.model_provider` metadata in rollout
  files when needed, with rollout backups;
- backfills missing SQLite thread rows and rebuilds `session_index.jsonl`;
- adopts local thread metadata to the active provider (`openai`, `cliproxy`, or
  `r9router`) so old conversations remain visible after switching.

Run it manually when needed:

```bash
cxsw repair-sessions --dry-run
cxsw repair-sessions
```

If Codex exits but your terminal does not show the native `codex resume <id>`
hint, the conversation is still recoverable as long as it was written to
`~/.codex/sessions/`:

```bash
cxsw last-resume
```

Set `CXSW_SESSION_SYNC=0` if you only want backend switching and no automatic
session metadata changes.

## Local State and Privacy

`cxsw init` snapshots your current native Codex config and auth file so native
mode can be restored if `~/.codex/auth.json` goes missing.

By default, state lives at:

```text
~/.local/state/cxsw/
```

That directory can contain private Codex auth material. It is intentionally not
part of the npm package or GitHub repository.

## Development

```bash
npm run check
npm run pack:dry
```

The npm package is published as `codex-cli-switcher`, exposes
`codex-cli-switcher`, `codex-switcher`, and `cxsw` through the `bin` field, and ships only:

- `cxsw`
- `lib/`
- `README.md`
- `LICENSE`
- `CHANGELOG.md`

## License

MIT
