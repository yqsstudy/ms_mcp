"""Version information for pt-snap."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pt-snap")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
