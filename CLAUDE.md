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
  jev.py       `search --play/--add`: asks TypeSafe's jev classifier which result matches the query
  errors.py    SonosToolError subclasses with exit codes (1 general, 2 auth, 3 config, 4 speaker)
tests/         pytest; no network, no speaker (fakes via monkeypatch, $SONOS_HOME for state)
scripts/play   sh wrapper: `play WORDS...` = `sonos search track WORDS... --play` (-a album, -q --add);
               symlinked into ~/.local/bin, not installed by uv
```

## Conventions

- Positions are 1-indexed at the CLI boundary and converted once in `cli.py`; `Player`
  methods take 0-based indexes.
- `actions.py` returns data, never formatted strings. Formatting lives in `cli.py`.
- Errors are raised as `SonosToolError` subclasses; `SonosGroup.invoke` prints them to
  stderr and exits with the class's exit code. Never `print()` from `actions.py`.
- No import-time side effects: speaker and music-service connections are created lazily,
  and the `typesafe_sdk` import lives inside `jev._ask`, reached only via `--play`/`--add`.
  Tests replace `jev._ask` (unit) or `jev.pick` (CLI); nothing calls TypeSafe offline.
- `jev.pick` builds one Choice question whose options are the search positions plus
  `none`; `none` means nothing is queued and the CLI exits 1. There is no confidence
  threshold on purpose (TypeSafe's guidance for pure selection is to take the top option);
  the confidence is reported so one can be added if real use shows the need.
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
- Every search goes to `catalog:universal:search` (SoCo category `all`), not to
  `catalog:tracks:search` / `catalog:albums:search`. The per-type searches resolve a query
  against one facet only: `traveling alone` and `jason isbell` each work, but
  `jason isbell traveling alone` returns a single wrong row, and
  `southeastern jason isbell` returns nothing. Word order does not matter and `index` /
  `count` do not help - Amazon reports its capped count as the true total. Do not
  "optimize" the category back to the per-type search.
- The universal response is mixed, so `search()` filters it by id prefix
  (`catalog:track:`, `catalog:album:`). Filter on the prefix, not on the SoCo class:
  podcast episodes arrive as `MSTrack` exactly like music does.
- jev picks with confidence around 0.6 to 0.7 even when it is clearly right. Amazon lists
  the same recording twice (two `Traveling Alone (Live)` rows, two `Southeastern` rows) and
  the rows are identical strings to jev, so the probability splits between them while
  covers, demos and remasters get 0.00. Checked live 2026-09-22. Do not add a confidence
  threshold to "fix" this; look at the `--json` probabilities instead.
- Track search results carry no album, so jev cannot tell two live recordings apart and
  neither can a person reading the list. The album shows up only after enqueueing
  (`sonos status`). Resolving albums first would cost one SMAPI call per result
  (`get_extended_metadata`) and has been judged not worth it.
- Neil Young had his catalog pulled from Amazon Music, so searching for his songs returns
  covers, karaoke and tribute versions but almost nothing by him. Checked 2026-09-22:
  of twelve canonical songs only `Heart of Gold (2009 Remaster)` and a 1985 live
  `The Needle and The Damage Done` survive, both licensing one-offs rather than album
  tracks. This looks like a search bug and is not one - do not use Neil Young (or any
  artist you have not confirmed is present) when testing search. Re-check before trusting
  this note; catalogs change.

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
Adding a dependency to `pyproject.toml` needs `uv tool install --editable . --reinstall`,
since the tool's venv is separate from `.venv`.

Live checks of `--play`/`--add` need `typesafe_api_key` in `~/.sonos/config.toml`; it is
already set on this machine. A pick costs a fraction of a cent.
