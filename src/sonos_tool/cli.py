"""`sonos` command-line interface.

Thin layer: parse arguments, call actions, print. Human-readable text by
default; `--json` switches every command to a single JSON document on stdout.
Errors go to stderr with a non-zero exit code.
"""

from __future__ import annotations

import json
import sys

import click
from soco.exceptions import SoCoException

from . import __version__, actions, config, store
from .errors import SonosToolError


class Context:
    def __init__(self, speaker: str | None, as_json: bool):
        self.speaker_flag = speaker
        self.as_json = as_json
        self._player: actions.Player | None = None

    def player(self) -> actions.Player:
        if self._player is None:
            name = config.resolve_speaker_name(self.speaker_flag)
            self._player = actions.Player(config.connect_speaker(name))
        return self._player

    def emit(self, data, text: str) -> None:
        if self.as_json:
            click.echo(json.dumps(data, indent=2))
        else:
            click.echo(text)


pass_ctx = click.make_pass_decorator(Context)


class SonosGroup(click.Group):
    """Group that maps domain errors to stderr + exit codes for every subcommand."""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except SonosToolError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(e.exit_code)
        except SoCoException as e:
            click.echo(f"Sonos error: {e}", err=True)
            sys.exit(1)
        except (ConnectionError, OSError) as e:
            click.echo(f"Network error talking to the speaker: {e}", err=True)
            sys.exit(4)


def _fmt_track(t: dict) -> str:
    """title - artist - album, omitting empty, unknown or redundant parts."""
    title, artist, album = (t.get(k, "") for k in ("title", "artist", "album"))
    if album == title:
        album = ""  # album search results carry album == title; don't print it twice
    return " - ".join(p for p in (title, artist, album) if p and not p.startswith("Unknown "))


def _numbered(items: list[dict]) -> str:
    return "\n".join(f"{i}. {_fmt_track(t)}" for i, t in enumerate(items, 1))


# --- root -------------------------------------------------------------------


@click.group(cls=SonosGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-s", "--speaker", metavar="NAME", help="Speaker to control (overrides config and $SONOS_SPEAKER).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.version_option(__version__, prog_name="sonos")
@click.pass_context
def cli(ctx, speaker, as_json):
    """Control Sonos speakers: search music, manage the queue, playlists and volume.

    Typical flow:  sonos search track heart of gold  ->  sonos queue add-track 2 --play
    """
    ctx.obj = Context(speaker, as_json)


# --- speakers ---------------------------------------------------------------


@cli.command()
@pass_ctx
def speakers(c: Context):
    """Discover all Sonos players on the network, grouped by system (S1/S2 household)."""
    data = config.discover_speakers()
    if not data:
        raise SonosToolError("No Sonos speakers found on the network.")
    lines = []
    for hh in dict.fromkeys(d["household"] for d in data):
        members = [d for d in data if d["household"] == hh]
        lines.append(f"{members[0]['generation']} system ({hh}):")
        lines.extend(f"  {d['name']}  ({d['ip']}, {d['model']})" for d in members)
    c.emit(data, "\n".join(lines))


@cli.group(invoke_without_command=True)
@pass_ctx
@click.pass_context
def speaker(ctx, c: Context):
    """Show or set the default speaker."""
    if ctx.invoked_subcommand is not None:
        return
    p = c.player()
    members = [m.player_name for m in p.device.group.members] if p.device.group else [p.name]
    data = {"speaker": p.name, "ip": p.device.ip_address, "group": members, "volume": p.volume()}
    grp = f" (grouped with {', '.join(m for m in members if m != p.name)})" if len(members) > 1 else ""
    c.emit(data, f"{p.name}{grp} at {p.device.ip_address}, volume {p.volume()}")


@speaker.command("set")
@click.argument("name")
@pass_ctx
def speaker_set(c: Context, name):
    """Persist NAME as the default speaker in ~/.sonos/config.toml."""
    device = config.connect_speaker(name)  # validates it exists
    config.set_default_speaker(device.player_name)
    c.emit({"speaker": device.player_name, "config": str(store.config_path())},
           f"Default speaker set to {device.player_name} ({store.config_path()})")


# --- playback ----------------------------------------------------------------


@cli.command()
@pass_ctx
def status(c: Context):
    """What is playing, transport state and volume."""
    s = c.player().status()
    state = s["state"].replace("_PLAYBACK", "").lower()
    if s.get("title"):
        where = f" [queue #{s['queue_position']}]" if s.get("queue_position") else ""
        text = (f"{state}: {s['title']} - {s['artist']} - {s['album']}{where} "
                f"({s['position']}/{s['duration']}), volume {s['volume']}"
                f"{', muted' if s['muted'] else ''}")
    else:
        text = f"Nothing playing on {s['speaker']} ({state}), volume {s['volume']}"
    c.emit(s, text)


@cli.command()
@click.argument("position", type=int, required=False)
@pass_ctx
def play(c: Context, position):
    """Resume playback, or play queue POSITION (1-indexed)."""
    p = c.player()
    if position is None:
        p.play()
        c.emit({"ok": True, "action": "play"}, "Playing")
        return
    length = p.queue_length()
    if not 1 <= position <= length:
        raise SonosToolError(f"Queue position {position} is out of range; the queue has {length} tracks.")
    p.play_from_queue(position - 1)
    c.emit({"ok": True, "action": "play", "position": position}, f"Playing queue position {position}")


@cli.command()
@pass_ctx
def pause(c: Context):
    """Pause playback."""
    c.player().pause()
    c.emit({"ok": True, "action": "pause"}, "Paused")


@cli.command()
@pass_ctx
def toggle(c: Context):
    """Toggle play/pause."""
    state = c.player().toggle()
    c.emit({"ok": True, "state": state}, state.capitalize())


@cli.command("next")
@pass_ctx
def next_track(c: Context):
    """Skip to the next track."""
    c.player().next()
    c.emit({"ok": True, "action": "next"}, "Skipped to next track")


# --- volume -------------------------------------------------------------------


@cli.command()
@click.argument("args", nargs=-1)
@pass_ctx
def volume(c: Context, args):
    """Show or change volume.

    \b
      sonos volume            show current level
      sonos volume 35         set level (0-100)
      sonos volume up [STEP]  raise by STEP (default 10)
      sonos volume down [STEP]
    """
    p = c.player()
    if not args:
        c.emit({"volume": p.volume()}, f"Volume {p.volume()}")
        return
    word = args[0].lower()
    if word in ("up", "down", "louder", "quieter"):
        step = 10
        if len(args) > 1:
            try:
                step = int(args[1])
            except ValueError:
                raise SonosToolError("STEP must be an integer.")
        delta = step if word in ("up", "louder") else -step
        level = p.adjust_volume(delta)
        c.emit({"volume": level}, f"Volume {level}")
        return
    try:
        level = int(word)
    except ValueError:
        raise SonosToolError("Usage: sonos volume [LEVEL | up [STEP] | down [STEP]]")
    if not 0 <= level <= 100:
        raise SonosToolError("LEVEL must be between 0 and 100.")
    p.set_volume(level)
    c.emit({"volume": level}, f"Volume {level}")


@cli.command()
@pass_ctx
def mute(c: Context):
    """Mute the speaker group."""
    c.player().set_mute(True)
    c.emit({"muted": True}, "Muted")


@cli.command()
@pass_ctx
def unmute(c: Context):
    """Unmute the speaker group."""
    c.player().set_mute(False)
    c.emit({"muted": False}, "Unmuted")


# --- search -------------------------------------------------------------------


@cli.group()
def search():
    """Search the music service. Results are numbered and cached for `queue add-*`."""


def _run_search(c: Context, kind: str, query: tuple[str, ...]):
    q = " ".join(query).strip()
    if not q:
        raise SonosToolError("QUERY is required.")
    items = actions.search(c.player().device, kind, q)
    if not items:
        c.emit([], f"No {kind}s found for '{q}'.")
        return
    noun = "album" if kind == "album" else "track"
    hint = (f"\n\nCheck artist and album before choosing; position 1 is not always the right one."
            f"\nNext: sonos queue add-{noun} POS [POS...] [--play]")
    c.emit(items, _numbered(items) + hint)


@search.command("track")
@click.argument("query", nargs=-1)
@pass_ctx
def search_track(c: Context, query):
    """Search tracks, e.g. `sonos search track thunder road bruce springsteen`."""
    _run_search(c, "track", query)


@search.command("album")
@click.argument("query", nargs=-1)
@pass_ctx
def search_album(c: Context, query):
    """Search albums, e.g. `sonos search album nebraska springsteen`."""
    _run_search(c, "album", query)


# --- queue --------------------------------------------------------------------


@cli.group(invoke_without_command=True)
@pass_ctx
@click.pass_context
def queue(ctx, c: Context):
    """Show the queue (default) or modify it with a subcommand."""
    if ctx.invoked_subcommand is not None:
        return
    p = c.player()
    items = p.queue()
    if not items:
        c.emit([], "Queue is empty")
        return
    current = p.status().get("queue_position", 0)
    lines = []
    for i, t in enumerate(items, 1):
        mark = "▶ " if i == current else "  "
        lines.append(f"{mark}{i}. {_fmt_track(t)}")
    for i, t in enumerate(items, 1):
        t["position"] = i
        t["playing"] = i == current
    c.emit(items, "\n".join(lines))


def _add_from_search(c: Context, kind: str, positions: tuple[int, ...], play: bool):
    if not positions:
        raise SonosToolError("At least one POS is required.")
    p = c.player()
    added = p.enqueue_search_results(kind, list(positions))
    lines = []
    data = []
    for item, first, count in added:
        if count > 1:
            where = f"queue positions {first}-{first + count - 1}"
        else:
            where = f"queue position {first}"
        label = f"album '{item['title']}'" if kind == "album" else f"'{item['title']}'"
        lines.append(f"Added {label} by {item['artist']} at {where}")
        data.append({**item, "first_position": first, "count": count})
    if play and added:
        first = added[0][1]
        p.play_from_queue(first - 1)
        lines.append(f"Playing from queue position {first}")
    c.emit({"added": data, "playing_from": added[0][1] if play and added else None}, "\n".join(lines))


@queue.command("add-track")
@click.argument("positions", nargs=-1, type=int)
@click.option("--play", is_flag=True, help="Start playing the first added track.")
@pass_ctx
def queue_add_track(c: Context, positions, play):
    """Add track(s) from the last track search by POSITION (1-indexed, multiple allowed)."""
    _add_from_search(c, "track", positions, play)


@queue.command("add-album")
@click.argument("positions", nargs=-1, type=int)
@click.option("--play", is_flag=True, help="Start playing the first added album.")
@pass_ctx
def queue_add_album(c: Context, positions, play):
    """Add album(s) from the last album search by POSITION (1-indexed, multiple allowed)."""
    _add_from_search(c, "album", positions, play)


@queue.command("remove")
@click.argument("position", type=int)
@pass_ctx
def queue_remove(c: Context, position):
    """Remove the track at POSITION (1-indexed)."""
    p = c.player()
    items = p.queue()
    if not 1 <= position <= len(items):
        raise SonosToolError(f"Queue position {position} is out of range; the queue has {len(items)} tracks.")
    removed = items[position - 1]
    p.remove_from_queue(position - 1)
    c.emit({"removed": removed, "position": position}, f"Removed {_fmt_track(removed)}")


@queue.command("clear")
@pass_ctx
def queue_clear(c: Context):
    """Remove everything from the queue."""
    c.player().clear_queue()
    c.emit({"ok": True}, "Queue cleared")


# --- playlists ----------------------------------------------------------------


@cli.group()
def playlist():
    """Local playlists (stored in ~/.sonos/playlists) and native Sonos playlists."""


@playlist.command("list")
@pass_ctx
def playlist_list(c: Context):
    """List local playlists."""
    names = store.list_playlists()
    if not names:
        c.emit([], "No local playlists. Create one with `sonos playlist add NAME --from-search POS`.")
        return
    c.emit(names, "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1)))


@playlist.command("show")
@click.argument("name")
@pass_ctx
def playlist_show(c: Context, name):
    """Show the tracks in local playlist NAME."""
    tracks = store.load_playlist(name)
    if not tracks:
        c.emit([], f"Playlist '{name}' is empty")
        return
    c.emit(tracks, f"Playlist '{name}' ({len(tracks)} tracks):\n" + _numbered(tracks))


@playlist.command("add")
@click.argument("name")
@click.option("--from-search", "from_search", type=int, metavar="POS", help="Position in the last track search.")
@click.option("--from-queue", "from_queue", type=int, metavar="POS", help="Position in the current queue.")
@pass_ctx
def playlist_add(c: Context, name, from_search, from_queue):
    """Add a track to local playlist NAME (created if missing)."""
    if (from_search is None) == (from_queue is None):
        raise SonosToolError("Give exactly one of --from-search POS or --from-queue POS.")
    if from_search is not None:
        item, length = actions.add_search_result_to_playlist(name, from_search)
    else:
        p = c.player()
        if from_queue < 1:
            raise SonosToolError("POS must be 1 or greater.")
        item = p.queue_item_as_playlist_entry(from_queue - 1)
        length = store.append_to_playlist(name, item)
    c.emit({"playlist": name, "added": item, "length": length},
           f"Added '{item['title']}' by {item['artist']} to playlist '{name}' ({length} tracks)")


@playlist.command("remove")
@click.argument("name")
@click.argument("position", type=int)
@pass_ctx
def playlist_remove(c: Context, name, position):
    """Remove the track at POSITION (1-indexed) from local playlist NAME."""
    removed = actions.remove_from_playlist(name, position)
    c.emit({"playlist": name, "removed": removed}, f"Removed '{removed.get('title')}' from playlist '{name}'")


@playlist.command("load")
@click.argument("name")
@click.option("--shuffle", is_flag=True, help="Add the tracks in random order.")
@click.option("--play", is_flag=True, help="Start playing from the first added track.")
@pass_ctx
def playlist_load(c: Context, name, shuffle, play):
    """Add all tracks of local playlist NAME to the queue."""
    p = c.player()
    first, count = p.enqueue_playlist(name, shuffle)
    text = f"Added {count} tracks from '{name}' at queue positions {first}-{first + count - 1}"
    if shuffle:
        text += " (shuffled)"
    if play:
        p.play_from_queue(first - 1)
        text += f"\nPlaying from queue position {first}"
    c.emit({"playlist": name, "first_position": first, "count": count, "shuffled": shuffle, "playing": play}, text)


@playlist.command("native")
@pass_ctx
def playlist_native(c: Context):
    """List native Sonos playlists (visible in the Sonos app)."""
    names = c.player().native_playlists()
    if not names:
        c.emit([], "No native Sonos playlists")
        return
    c.emit(names, "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1)))


@playlist.command("export")
@click.argument("name")
@click.option("--as", "native_name", metavar="NATIVE_NAME", help="Name for the native playlist (default: NAME).")
@pass_ctx
def playlist_export(c: Context, name, native_name):
    """Create a native Sonos playlist from local playlist NAME.

    Uses the queue temporarily and restores it afterwards.
    """
    target = c.player().create_native_playlist_from_local(name, native_name)
    c.emit({"local": name, "native": target}, f"Created native Sonos playlist '{target}' from '{name}'")



# --- music service authorization -----------------------------------------------


@cli.command()
@click.option("--complete", "complete", is_flag=True, help="Finish an authorization started earlier.")
@click.option("--status", "show_status", is_flag=True, help="Report whether this machine is authorized.")
@pass_ctx
def auth(c: Context, complete, show_status):
    """Link the music service (Amazon Music) for searches from this machine.

    Needed once per machine and per Sonos household (S1 and S2 systems are separate).
    Prints a sign-in link; after you sign in, the token is saved so `sonos search` works.
    In a terminal the command waits for you; from a script run `sonos auth`, sign in,
    then `sonos auth --complete`.
    """
    device = c.player().device
    if show_status:
        ms = actions.music_service(device)
        ok = actions.has_token(ms, device)
        data = {"service": config.music_service_name(), "speaker": device.player_name,
                "household": device.household_id, "auth_type": ms.auth_type, "authorized": ok}
        c.emit(data, f"{data['service']} for household of '{device.player_name}': "
                     f"{'authorized' if ok else 'NOT authorized (run `sonos auth`)'}")
        return
    if complete:
        pending = store.load_pending_auth()
        if not pending:
            raise SonosToolError("No authorization in progress. Run `sonos auth` first.")
        actions.complete_auth(device, pending)
        store.clear_pending_auth()
        c.emit({"authorized": True, "household": device.household_id},
               f"Authorized {config.music_service_name()} for the household of '{device.player_name}'.")
        return
    pending = actions.begin_auth(device)
    store.save_pending_auth(pending)
    text = (f"Sign in to {config.music_service_name()} at:\n\n  {pending['url']}\n\n"
            f"(link code {pending['link_code']}, household of '{device.player_name}')")
    if c.as_json or not sys.stdin.isatty():
        c.emit({**pending, "next": "sonos auth --complete"}, text + "\n\nThen run: sonos auth --complete")
        return
    click.echo(text)
    click.pause("Press Enter after you have signed in...")
    actions.complete_auth(device, pending)
    store.clear_pending_auth()
    click.echo(f"Authorized {config.music_service_name()} for the household of '{device.player_name}'.")


def main():
    cli()


if __name__ == "__main__":
    main()
