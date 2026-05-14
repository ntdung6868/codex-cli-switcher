# codex-switcher

`codex-switcher` is a macOS command-line switcher for routing the OpenAI Codex CLI
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
- Import and sync Codex OAuth account JSON files into CLIProxyAPI and 9Router.
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
npm install -g @ntdung6868/codex-switcher
cxsw init
```

Then open the menu:

```bash
cxsw
```

You can also run directly from a cloned repository:

```bash
git clone https://github.com/ntdung6868/codex-switcher.git
cd codex-switcher
./cxsw
```

## Quick Start

```bash
cxsw status
cxsw use cliproxy
cxsw use 9router
cxsw use native
```

By default, `cxsw use <mode>` updates Codex CLI configuration only. If Codex.app
is running, restart it so the app-server reads the new backend:

```bash
cxsw use --relaunch cliproxy
cxsw relaunch-app
cxsw quit-app
```

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
cxsw current                 # print only the active mode

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

cxsw import-backup-cliproxy  # backup OAuth JSON files to CLIProxyAPI dir
cxsw import-backup-9router   # backup OAuth JSON files to 9Router SQLite
cxsw sync-cliproxy-9router   # CLIProxyAPI auth dir to 9Router SQLite
```

## Configuration

| Environment variable | Default |
| --- | --- |
| `CXSW_STATE_DIR` | `${XDG_STATE_HOME:-$HOME/.local/state}/cxsw` |
| `CODEX_SWITCHER_DIR` | legacy alias for `CXSW_STATE_DIR` |
| `CODEX_HOME` | `$HOME/.codex` |
| `CLIPROXY_AUTH_DIR` | `$HOME/.cli-proxy-api` |
| `CLIPROXY_BASE_URL` | `http://127.0.0.1:8317/v1` |
| `CLIPROXY_API_KEY` | `your-api-key-1` |
| `NINEROUTER_DB` | `$HOME/.9router/db/data.sqlite` |
| `NINEROUTER_BASE_URL` | `http://127.0.0.1:20128/v1` |
| `NINEROUTER_API_KEY` | `sk_9router` |
| `CLIPROXY_BACKUP_DIR` | `$HOME/Documents/Backups/codex-oauth-backup/cli-proxy-api-auth` |
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
env_key = "CLIPROXY_API_KEY"
# === cxsw managed: provider block end ===
```

Switching back to `native` removes only those managed regions. Your other Codex
settings are left unchanged.

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

The npm package is published as `@ntdung6868/codex-switcher`, exposes both
`codex-switcher` and `cxsw` through the `bin` field, and ships only:

- `cxsw`
- `lib/`
- `README.md`
- `LICENSE`
- `CHANGELOG.md`

## License

MIT
