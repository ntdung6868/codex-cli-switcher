# Changelog

## 1.0.7 - 2026-05-18

- Normalize failed backend health probes to `HTTP 000` instead of the duplicated
  `HTTP 000000` display when curl reports no HTTP response.

## 1.0.6 - 2026-05-18

- Add `cxsw codex-status` and include the same check in `cxsw status` so users
  can verify that the plain `codex` command still points to the official
  `@openai/codex` CLI, not a `cxsw` wrapper.
- Keep `cxsw` strictly as a backend/session helper: no aliasing, wrapping, or
  patching of the official Codex CLI command.

## 1.0.5 - 2026-05-18

- Add `cxsw last-resume` and show the latest resume command in `cxsw status` so
  users can recover the `codex resume <id>` command even if the terminal does
  not display Codex's native exit hint.

## 1.0.4 - 2026-05-16

- Add a proxy plugin guard that disables non-bundled app-backed plugins in
  `cliproxy`/`9router` modes and restores them when returning to `native`. This
  prevents `codex_apps` MCP startup from failing on a stale native
  `~/.codex/auth.json` OAuth token while model calls are proxied.
- Add live-session preflight for `cxsw use`: by default it now refuses unsafe
  switches while Codex.app or an interactive `codex` session is still running.
  Use `--relaunch`, `--quit-app`, `--hot-reload`, or the explicit
  `--allow-live-sessions` override.
- Keep the unsafe 9Router Codex OAuth import paths behind
  `ALLOW_UNSAFE_9ROUTER_CODEX_IMPORT` so CLIProxyAPI remains the single
  refresher for Codex OAuth files.

## 1.0.3 - 2026-05-16

- Fix `{"error":{"message":"Invalid JSON body",...}}` from 9router when resuming a large/continued conversation. Root cause: Codex CLI gzip-compresses large request bodies, and 9router does not decompress gzip request bodies (a fresh short prompt stays uncompressed and works, which is why the config looked fine).
- Add `lib/ungzip-proxy.py`, a dependency-free loopback shim that decompresses Codex request bodies and streams responses (SSE-safe) before 9router.
- `cxsw use 9router` now starts the shim and points Codex at it; `cxsw use cliproxy|native` stops it. Add `cxsw shim {status|start|stop|restart}`, `CXSW_9ROUTER_SHIM`, `NINEROUTER_SHIM_PORT`, and `NINEROUTER_UPSTREAM_URL` (legacy alias: `NINEROUTER_BASE_URL`).

## 1.0.2 - 2026-05-15

- Add `cxsw repair-sessions` to rebuild Codex local session indexes and keep old threads visible after backend/account switches.
- Run session repair automatically after `cxsw use <mode>` unless `CXSW_SESSION_SYNC=0` is set.

## 1.0.1 - 2026-05-14

- Fix proxy mode auth so Codex CLI no longer exits with missing `CLIPROXY_API_KEY` or `NINEROUTER_API_KEY` after npm install.
- Generate Codex provider `auth.command` entries that use environment overrides when present and fall back to the local default proxy tokens.

## 1.0.0 - 2026-05-14

- Initial public release.
- Add interactive backend switching for native ChatGPT, CLIProxyAPI, and 9Router.
- Preserve unmanaged Codex CLI configuration by editing only marked TOML blocks.
- Add health checks, Codex.app restart helpers, plugin doctor, and OAuth import/sync helpers.
- Package `cxsw` as an npm global CLI.
