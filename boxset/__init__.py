"""boxset: build a Blu-ray collection disc with a themed menu from your own rips."""
try:
    from ._version import __version__      # written by the release build from the tag
except ImportError:
    __version__ = "0.0.0"                  # running from source
