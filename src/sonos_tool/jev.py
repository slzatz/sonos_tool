"""Pick the best search result with TypeSafe's jev model.

jev is a classifier, not a chat model: given a state and a Choice question it returns
one option plus a probability per option and a confidence. Here the options are the
numbered search results and the state is what the user asked for, so
`sonos search track ... --play` can go straight from a query to playback.

Nothing here runs at import time and the SDK is imported lazily, so `sonos` without a
TypeSafe key starts as fast as before. Functions return data; the CLI formats it.
"""

from __future__ import annotations

import os

from . import config, store
from .errors import ConfigError, SonosToolError

API_KEY_ENV = "TYPESAFE_API_KEY"
CONFIG_KEY = "typesafe_api_key"
NONE_OPTION = "none"
TIMEOUT_SECONDS = 10.0

INSTRUCTIONS = {
    "track": (
        "The user asked a music player to play a track, described in `request`. The options "
        "are the search results, each as 'title - artist - album'. Pick the result that is "
        "the recording the user meant. Prefer the artist named in the request. Prefer the "
        "original studio recording unless the request asks for a live, acoustic, remastered, "
        "demo, deluxe or other specific version. Never pick a cover, karaoke, tribute, "
        "instrumental or sound-alike version unless the request asks for one. "
        f"Pick '{NONE_OPTION}' if no result is the track the user asked for."
    ),
    "album": (
        "The user asked a music player to play an album, described in `request`. The options "
        "are the search results, each as 'title - artist'. Pick the result that is the album "
        "the user meant. Prefer the artist named in the request. Prefer the original release "
        "unless the request asks for a live, deluxe, remastered, anniversary or other specific "
        "edition. Never pick a tribute, karaoke or cover album unless the request asks for one. "
        f"Pick '{NONE_OPTION}' if no result is the album the user asked for."
    ),
}


def api_key() -> str:
    """The TypeSafe API key: $TYPESAFE_API_KEY, else `typesafe_api_key` in config.toml."""
    key = os.environ.get(API_KEY_ENV) or config.load_config().get(CONFIG_KEY)
    if not key:
        raise ConfigError(
            f"No TypeSafe API key. Set ${API_KEY_ENV} or add {CONFIG_KEY} = \"...\" to "
            f"{store.config_path()} (keys: https://console.typesafe.ai/keys)."
        )
    return str(key)


def _describe(kind: str, item: dict) -> str:
    parts = [item.get("title", ""), item.get("artist", "")]
    if kind == "track" and item.get("album") and item["album"] != item.get("title"):
        parts.append(item["album"])
    return " - ".join(p for p in parts if p)


def _ask(key: str, state: dict, instructions: str, criteria: dict):
    """One jev call. Separated so tests can replace it without an SDK client."""
    from typesafe_sdk import Choice, TypeSafeClient  # lazy: only --play/--add pays for it

    with TypeSafeClient(api_key=key, timeout=TIMEOUT_SECONDS) as client:
        response = client.system_one(
            state=state,
            questions={"pick": Choice(instructions=instructions, criteria=criteria)},
        )
    answer = response.choices["pick"]
    return answer.choice, float(answer.confidence), dict(answer.probabilities)


def pick(kind: str, query: str, items: list[dict]) -> dict:
    """Ask jev which of `items` (the last `kind` search) the user meant by `query`.

    Returns {"position": int | None, "confidence": float, "probabilities": {"1": p, ...}}.
    position is 1-indexed; None means jev chose 'none of these'.
    """
    if kind not in INSTRUCTIONS:
        raise ValueError(f"unknown search kind {kind!r}")
    key = api_key()
    criteria = {str(i): _describe(kind, item) for i, item in enumerate(items, 1)}
    criteria[NONE_OPTION] = f"No result is the {kind} the user asked for"
    state = {"request": query, "kind": kind}

    try:
        choice, confidence, probabilities = _ask(key, state, INSTRUCTIONS[kind], criteria)
    except SonosToolError:
        raise
    except ModuleNotFoundError as e:
        raise ConfigError(
            f"{e}. The installed `sonos` predates this dependency; from the repository run "
            "`uv tool install --editable . --reinstall`."
        ) from e
    except Exception as e:  # SDK errors are many; map them all to one exit code
        name = type(e).__name__
        if "Authentication" in name or "PermissionDenied" in name:
            raise SonosToolError(
                f"TypeSafe rejected the API key ({e}). Check ${API_KEY_ENV} / {CONFIG_KEY}."
            ) from e
        raise SonosToolError(f"TypeSafe request failed: {e}") from e

    position = None if choice == NONE_OPTION else int(choice)
    return {"position": position, "confidence": confidence, "probabilities": probabilities}
