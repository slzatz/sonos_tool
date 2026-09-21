# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`sonos` is a click-based CLI for Sonos speakers, built on the SoCo library, meant to be
driven equally by people and by AI agents. It replaced an earlier MCP server plus a tmux
TUI; do not reintroduce either. There is one command surface, documented in `README.md`
and mirrored for agents in `.claude/skills/sonos/SKILL.md`. Keep those two in sync with
`cli.py` whenever a command or its output changes.

## Layout

```
src/sonos_tool/
  cli.py       click group and subcommands; parses args, calls actions, prints (text or --json)
  actions.py   SoCo operations: Player class (one speaker), search, auth, playlist helpers
  config.py    ~/.sonos/config.toml, speaker resolution (IP cache -> multicast -> subnet scan)
  store.py     paths and JSON I/O under ~/.sonos (search results, playlists, caches)
  didl.py      the one DIDL-Lite template used to enqueue music-service items
  errors.py    SonosToolError subclasses with exit codes (1 general, 2 auth, 3 config, 4 speaker)
tests/         pytest; no network, no speaker (fakes via monkeypatch, $SONOS_HOME for state)
```

## Conventions

- Positions are 1-indexed at the CLI boundary and converted once in `cli.py`; `Player`
  methods take 0-based indexes.
- `actions.py` returns data, never formatted strings. Formatting lives in `cli.py`.
- Errors are raised as `SonosToolError` subclasses; `SonosGroup.invoke` prints them to
  stderr and exits with the class's exit code. Never `print()` from `actions.py`.
- No import-time side effects: speaker and music-service connections are created lazily.
- Every command must work with `--json` and produce one JSON document.
- Runtime state stays under `~/.sonos` (override with `$SONOS_HOME`); the music-service
  token is SoCo's `~/.config/SoCo/token_store.json` (override with `$SONOS_TOKEN_STORE`).
  Local playlists are extensionless files whose name is the playlist name; keep that.

## Things that look like bugs but are not

- Amazon catalog ids are colon-style (`catalog:track:asin:...`). Sonos accepts an enqueue
  only when the DIDL item id is the URL-quoted id and the URI is the double-quoted
  `soco://0fffffff...` form SoCo returns. Do not "normalize" either without testing on a
  real speaker.
- Track search results have no album field any more; the CLI omits empty columns.
- `AddURIToQueue` sometimes fails with UPnP 800 for a valid item; `Player.enqueue` retries.
- Networks can host two Sonos households (S1 legacy and S2 current). Multicast discovery
  returns only the first to answer, so discovery uses `scan_network(multi_household=True)`
  and the music service is bound to the configured speaker's household. The SMAPI token
  is per household; a missing one is a deterministic 401, fixed by `sonos auth`.
- Some artists are absent from Amazon Music (Neil Young, for example); their searches
  return only covers. Use another artist when testing search.

## Working on it

```bash
uv sync --extra dev
uv run pytest -q          # fast, offline
uv run sonos --help
```

Live checks need a speaker on the LAN and change its queue; add tracks, verify, then
remove them and restore the previous playing position. Never leave test playlists in
`~/.sonos/playlists` (use names like `zz_test` and delete them).

Install for daily use with `uv tool install --editable .`; the installed command then
tracks the working tree, so a broken edit breaks `sonos` immediately. Run the tests first.
