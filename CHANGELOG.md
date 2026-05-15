# Changelog

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
