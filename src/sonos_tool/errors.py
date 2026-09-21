"""Exceptions raised by sonos_tool. The CLI maps these to stderr messages and exit codes."""


class SonosToolError(Exception):
    """Base class. exit_code is what the CLI exits with."""

    exit_code = 1


class ConfigError(SonosToolError):
    """Missing or invalid configuration (no speaker configured, bad config file)."""

    exit_code = 3


class SpeakerNotFound(SonosToolError):
    """The configured speaker could not be found on the network."""

    exit_code = 4


class AuthError(SonosToolError):
    """The music service rejected the request (typically expired authorization)."""

    exit_code = 2


class NoSearchResults(SonosToolError):
    """A queue/playlist add was attempted before a matching search was run."""

    exit_code = 1
