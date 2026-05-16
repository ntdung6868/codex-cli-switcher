# Changelog

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
