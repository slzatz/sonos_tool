# sonos_tool

A command-line tool for controlling Sonos speakers, designed to be equally usable by
a person at a terminal and by an AI agent running shell commands.

```
sonos search track thunder road springsteen
sonos queue add-track 1 --play
sonos search track live traveling alone jason isbell --play   # jev picks the match
sonos volume down
sonos status
```

Music search uses the music service configured on your Sonos system (Amazon Music by
default) through the [SoCo](https://github.com/SoCo/SoCo) library.

## Install on a fresh machine (Linux or macOS)

Prerequisites: `git` (macOS offers to install it on first use), a Sonos system on the
same network as this machine, and a music service already linked to that Sonos system
in the Sonos app (Amazon Music by default).

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

   `uv tool update-shell` checks whether uv's tool directory (`uv tool dir --bin`, normally
   `~/.local/bin`) is on your `PATH` and, if not, appends an `export PATH=...` line to your
   shell's startup file (`~/.zshrc` on macOS, `~/.bashrc` on most Linux setups). It is safe to
   run repeatedly and changes nothing if the directory is already on `PATH`. The edit only
   applies to new shells, so open a new terminal before the next step. Homebrew's `uv` still
   needs this step, because tool commands go to `~/.local/bin` regardless of where `uv` lives.

   On macOS the first `sonos speakers` may trigger a firewall prompt asking whether Python
   may accept incoming connections; allow it, since discovery listens for replies from the
   speakers.
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

5. Optional: let `sonos search ... --play` pick the result for you. Get a
   [TypeSafe](https://typesafe.ai) API key from https://console.typesafe.ai/keys and either
   `export TYPESAFE_API_KEY=...` in your shell startup file or add
   `typesafe_api_key = "..."` to `~/.sonos/config.toml`. Without a key everything else works
   and `--play` / `--add` exit with code 3. On a machine where `sonos` was installed before
   this feature existed, run `uv tool install --editable . --reinstall` first; the error
   `No module named typesafe_sdk` means exactly that.

To update later: `cd ~/sonos_tool && git pull` (the editable install picks up code changes;
if `pyproject.toml` gained a dependency, also run `uv tool install --editable . --reinstall`).
To remove: `uv tool uninstall sonos-tool` and delete `~/.sonos` if you want the playlists gone too.

## Configuration

`~/.sonos/config.toml`:

```toml
speaker = "Living Room"
music_service = "Amazon Music"
typesafe_api_key = "..."      # optional; $TYPESAFE_API_KEY takes precedence
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
| `sonos search track QUERY... --play` | Search, let jev pick the best match, queue it and play it |
| `sonos search album QUERY... --add` | Same, but only add the pick to the queue (`--add` works for tracks too) |
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

Queries match artist and title together, so naming both is the way to narrow a search:
`sonos search track traveling alone jason isbell` finds the right recording where
`traveling alone` alone returns every cover of it. A search returns up to about 18
tracks or 9 albums.

```
$ sonos search album nebraska springsteen
1. Nebraska - Bruce Springsteen
2. Live from Nowhere: Songs from Bruce Springsteen's Nebraska - Danny Golden
...
$ sonos queue add-album 1 --play
Added album 'Nebraska' by Bruce Springsteen at queue positions 1-10
Playing from queue position 1
```

Position 1 is often but not always the right result, so read the artist and album
columns before choosing.

### Letting jev choose: `--play` and `--add`

`sonos search track QUERY --play` does the reading for you. The numbered results are sent
to [jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev), TypeSafe's
classifier model, as the options of one multiple-choice question whose state is your
query; jev answers with a position, a probability per option and a confidence, in well
under a second. The chosen result is added to the queue and played (`--add` only queues
it). The list is still printed, followed by the pick, so a wrong pick is one
`sonos queue add-track POS --play` away.

```
$ sonos search track live traveling alone jason isbell --play
1. Traveling Alone - Jason Isbell - Southeastern
2. Traveling Alone (Live) - Jason Isbell - Live from the Ryman
3. Traveling Alone - Some Cover Band - Isbell Tribute
Picked 2 (confidence 0.91): Traveling Alone (Live) - Jason Isbell - Live from the Ryman
Added 'Traveling Alone (Live)' by Jason Isbell at queue position 14
Playing from queue position 14
```

jev is told to prefer the named artist and the original studio recording unless the
query asks for a live, remastered or other specific version, and never to pick covers,
karaoke or tribute versions. It may also answer that nothing fits (for example when an
artist is not in the catalog and every result is a cover); then nothing is queued, the
list is printed, and the command exits 1 with a message pointing at the manual flow.

This needs a TypeSafe API key (`$TYPESAFE_API_KEY` or `typesafe_api_key` in the config
file); a missing key exits 3 before the speaker is touched.

For typing at a terminal, `scripts/play` is a tiny shell wrapper so that
`play live jason isbell traveling alone` runs the track command above, `play -a southeastern`
runs the album one, and `play -q ...` uses `--add`. Link it onto your PATH once:

```bash
ln -s ~/sonos_tool/scripts/play ~/.local/bin/play
``` A pick costs a fraction of a
cent. With `--json` the document is `{"results", "pick": {"position", "confidence",
"probabilities"}, "added", "playing_from"}`.

## For agents

The file `.claude/skills/sonos/SKILL.md` is a ready-made Claude Code skill describing
this CLI. Copy or symlink it into any project's `.claude/skills/` directory and allow
`Bash(sonos:*)` in that project's permissions.

Output conventions that make the tool easy to drive programmatically:

- Results on stdout, errors on stderr.
- Exit codes: 0 success, 1 general error, 2 music service not authorized or rejected the
  request, 3 configuration missing, 4 speaker unreachable.
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

- **Search results look wrong for a well-known artist**: covers, karaoke versions and
  tribute albums are common and sometimes outrank the original, so read the artist column
  rather than taking position 1. If *nothing* by the artist shows up, they may not be on
  Amazon Music at all - Neil Young had his catalog pulled, so his songs return only other
  people's versions. That is the catalog, not the tool.

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
