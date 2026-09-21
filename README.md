# sonos_tool

A command-line tool for controlling Sonos speakers, designed to be equally usable by
a person at a terminal and by an AI agent running shell commands.

```
sonos search track heart of gold neil young
sonos queue add-track 2 --play
sonos volume down
sonos status
```

Music search uses the music service configured on your Sonos system (Amazon Music by
default) through the [SoCo](https://github.com/SoCo/SoCo) library.

## Install on a fresh machine (Linux or macOS)

1. Install [uv](https://docs.astral.sh/uv/) if you do not have it:
   `brew install uv` on macOS, `pacman -S uv` on Arch, or
   `curl -LsSf https://astral.sh/uv/install.sh | sh` anywhere.
2. Clone and install. Python 3.13 is downloaded automatically if missing.
   ```bash
   git clone https://github.com/slzatz/sonos_tool.git ~/sonos_tool
   cd ~/sonos_tool
   uv tool install --editable .        # installs the `sonos` command into ~/.local/bin
   uv tool update-shell                # adds ~/.local/bin to PATH if needed; reopen the shell
   ```
   (`pipx install --editable .` works too.)
3. Be on the same network as the speakers, then pick your default speaker:
   ```bash
   sonos speakers                      # every player, grouped by S1/S2 system
   sonos speaker set "Living Room"    # saved to ~/.sonos/config.toml
   ```
4. Link the music service once so searches work from this machine:
   ```bash
   sonos auth                          # prints an Amazon sign-in link and waits
   sonos auth --status                 # confirm
   ```
   The token is stored per machine **and per Sonos household** in
   `~/.config/SoCo/token_store.json`. If you later switch the default speaker to one in
   a different household (S1 vs S2), run `sonos auth` again for that household.

To update later: `cd ~/sonos_tool && git pull` (the editable install picks up changes).

## Configuration

`~/.sonos/config.toml`:

```toml
speaker = "Living Room"
music_service = "Amazon Music"
```

Speaker precedence for any single command: `--speaker NAME` flag, then `$SONOS_SPEAKER`,
then the config file. The speaker's IP is cached in `~/.sonos/speaker_cache.json` so
most commands skip network discovery entirely.

## Commands

Every command supports `--help`. Positions are always 1-indexed, as displayed.
Add `--json` before the command for machine-readable output.

| Command | What it does |
|---|---|
| `sonos speakers` | Discover all Sonos players on the LAN, grouped by system (S1/S2) |
| `sonos auth [--status] [--complete]` | Link the music service for searches from this machine |
| `sonos speaker` | Show the default speaker, its group and volume |
| `sonos speaker set NAME` | Persist NAME as the default speaker |
| `sonos status` | Transport state, current track, volume |
| `sonos play [POS]` | Resume, or play queue position POS |
| `sonos pause` / `sonos toggle` / `sonos next` | Transport control |
| `sonos volume` | Show volume |
| `sonos volume 35` | Set volume 0-100 |
| `sonos volume up [STEP]` / `down [STEP]` | Adjust (default step 10) |
| `sonos mute` / `sonos unmute` | Mute the group |
| `sonos search track QUERY...` | Search tracks; results numbered and cached |
| `sonos search album QUERY...` | Search albums; results numbered and cached |
| `sonos queue` | Show the queue (▶ marks the playing track) |
| `sonos queue add-track POS [POS...] [--play]` | Add track(s) from the last track search |
| `sonos queue add-album POS [POS...] [--play]` | Add album(s) from the last album search |
| `sonos queue remove POS` | Remove one queue entry |
| `sonos queue clear` | Empty the queue |
| `sonos playlist list` | List local playlists |
| `sonos playlist show NAME` | Show a local playlist |
| `sonos playlist add NAME --from-search POS` | Save a searched track into a local playlist |
| `sonos playlist add NAME --from-queue POS` | Save a queued track into a local playlist |
| `sonos playlist remove NAME POS` | Remove a track from a local playlist |
| `sonos playlist load NAME [--shuffle] [--play]` | Add a local playlist to the queue |
| `sonos playlist native` | List native Sonos playlists |
| `sonos playlist export NAME [--as NATIVE_NAME]` | Create a native Sonos playlist from a local one |

### The search-then-add flow

Searching never changes the speaker. It prints a numbered list and caches it to
`~/.sonos/search_results/`. A following `queue add-track` or `queue add-album` refers to
those numbers. Several positions can be given at once, and `--play` starts playback from
the first item added.

```
$ sonos search album harvest neil young
1. Harvest - Neil Young
2. Harvest Moon - Neil Young
3. Harvest (2009 Remaster) - Neil Young
...
$ sonos queue add-album 1 --play
Added album 'Harvest' by Neil Young at queue positions 1-10
Playing from queue position 1
```

Position 1 is often but not always the right result, so read the artist and album
columns before choosing.

## For agents

The file `.claude/skills/sonos/SKILL.md` is a ready-made Claude Code skill describing
this CLI. Copy or symlink it into any project's `.claude/skills/` directory and allow
`Bash(sonos:*)` in that project's permissions.

Output conventions that make the tool easy to drive programmatically:

- Results on stdout, errors on stderr.
- Exit codes: 0 success, 1 general error, 2 music-service authorization expired,
  3 configuration missing, 4 speaker unreachable.
- `--json` gives one JSON document per command.

## Runtime files

```
~/.sonos/config.toml                       speaker and music service
~/.sonos/speaker_cache.json                {name: ip}
~/.sonos/pending_auth.json                 present only between `sonos auth` and `--complete`
~/.config/SoCo/token_store.json            music-service token, per household (written by SoCo)
~/.sonos/search_results/track_search.json  last track search
~/.sonos/search_results/album_search.json  last album search
~/.sonos/playlists/<name>                  local playlists (JSON list; filename is the name)
```

Local playlist entries and search results share one shape:
`{"title", "artist", "album", "item_id", "uri"}`.

## Two Sonos systems on one network

Households running the legacy S1 app and the current S2 app are separate systems
that share a LAN. Sonos multicast discovery answers with only the household that
responds first, so `sonos speakers` instead scans the subnet and lists every
household, labelled S1 or S2. Looking a speaker up by name falls back to the same
scan, so `sonos speaker set` works for either system. Once a speaker's IP is cached
no discovery runs at all. Use `--speaker NAME` to address a speaker in the other
system for a single command.

## Troubleshooting

- **"not authorized for the Sonos household of ..."** (exit 2): run `sonos auth`. Searches
  are made through your default speaker's household and each household needs its own
  link on each machine.
- **"rejected the request (authorization expired or temporarily unavailable)"** (exit 2):
  the tool already retried with backoff. Wait a moment and retry; if it keeps failing,
  run `sonos auth` again.
- **"Sonos refused to enqueue ..."**: the speaker's own lookup of the item with the music
  service failed (UPnP error 800). This is also intermittent and is retried; run the
  add command again.
- **"Could not find a Sonos speaker named ..."** (exit 4): run `sonos speakers`; names are
  case-sensitive. The cache in `~/.sonos/speaker_cache.json` can be deleted safely.
- **No speakers discovered**: the machine must be on the same network/VLAN as the
  speakers. The subnet scan assumes a /24 or smaller network; multicast is the fallback.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run sonos --help
```
