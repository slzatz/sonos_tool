---
name: sonos
description: Control Sonos speakers with the `sonos` CLI - play music by searching tracks or albums, manage the queue and playlists, adjust volume, check what is playing. Use whenever the user asks to play, pause, skip, search for, or queue music, or mentions Sonos, speakers, or volume.
---

# Sonos control via the `sonos` CLI

Everything goes through one command, `sonos`, run with the Bash tool. Every subcommand has
`--help`. Positions are 1-indexed exactly as displayed. Results print on stdout, errors on
stderr with a non-zero exit code. Add `--json` before the subcommand for JSON output.

## Playing something the user asked for

1. Decide track vs album from the request ("play Heart of Gold" is a track; "play Harvest" or
   "play the album ..." is an album).
2. Search. Include the artist when you know it - the query matches artist and title
   together, so naming both narrows the results rather than restricting them.
   ```
   sonos search track thunder road bruce springsteen
   sonos search album nebraska springsteen
   ```
3. Read the numbered results. **Position 1 is not always right**: check the artist and album
   columns (live versions, covers, tribute albums and remasters are common). Briefly tell the
   user which one you picked and why if it was not obvious.
4. Add and play in one step:
   ```
   sonos queue add-track 3 --play
   sonos queue add-album 1 --play
   ```
   Several positions may be given at once (`sonos queue add-track 2 5 9`). Albums expand to
   all their tracks; the output reports the queue positions used.

Without `--play` the items are appended to the queue and playback is unchanged, which is
what "add X to the queue" means. Use `sonos play POS` to start at a specific position later.

## Command reference

| Need | Command |
|---|---|
| What is playing | `sonos status` |
| Resume / pause / toggle / skip | `sonos play`, `sonos pause`, `sonos toggle`, `sonos next` |
| Play queue item N | `sonos play N` |
| Show queue | `sonos queue` (▶ marks the playing track) |
| Remove / clear queue | `sonos queue remove N`, `sonos queue clear` |
| Volume | `sonos volume` (show), `sonos volume 35`, `sonos volume up`, `sonos volume down 5` |
| Mute | `sonos mute`, `sonos unmute` |
| Search | `sonos search track WORDS...`, `sonos search album WORDS...` |
| Add from last search | `sonos queue add-track N [N...] [--play]`, `sonos queue add-album N [N...] [--play]` |
| Local playlists | `sonos playlist list`, `sonos playlist show NAME` |
| Save a track to a playlist | `sonos playlist add NAME --from-search N` or `--from-queue N` |
| Remove from playlist | `sonos playlist remove NAME N` |
| Play a playlist | `sonos playlist load NAME [--shuffle] [--play]` |
| Native Sonos playlists | `sonos playlist native`, `sonos playlist export NAME [--as NEW_NAME]` |
| Speakers | `sonos speakers` (discover), `sonos speaker` (current), `sonos speaker set NAME` |
| One-off other speaker | `sonos -s "Kitchen" volume 20` |

"Turn it up/down" means `sonos volume up` / `sonos volume down` (step 10). "Louder a little"
is `sonos volume up 5`.

## Interpreting results and errors

- `sonos search ...` returns nothing: try fewer words (drop "the", drop the album name, or
  search by artist and title only) before telling the user it was not found.
- A search returns up to about 18 tracks or 9 albums, so a common title may not show every
  recording of it. Add the artist to the query rather than paging - there is no paging.
- If every result is a cover, karaoke or tribute version, the artist may not be in the
  catalog at all (Neil Young pulled his, for one). Say so rather than queueing a cover the
  user did not ask for.
- Exit code 2, "not authorized for the Sonos household": this machine has not linked the
  music service for that household. Tell the user to run `sonos auth` in a terminal (it
  needs a browser sign-in); do not attempt it yourself.
- Exit code 2, "rejected the request": the tool already retried with backoff. Wait a few
  seconds and retry once; if it still fails, tell the user to run `sonos auth`.
- Exit code 4, speaker not found: run `sonos speakers` and report the available names.
- Exit code 3, no speaker configured: run `sonos speakers` then `sonos speaker set NAME`.
- Search results are cached per kind (track or album). A new search of the same kind
  replaces the previous numbering, so add items before searching again.

## Responding to the user

Confirm what happened in one line using the tool's output, e.g. "Playing Thunder Road by
Bruce Springsteen from Born to Run." Do not paste raw command output unless the user asked
to see a list (queue, search results, playlists).
