"""CFDICT-Next — Chinese-French dictionary tooling."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Installed wheel/sdist: single source of truth is pyproject version.
    __version__ = version("cxdict")
except PackageNotFoundError:  # dev checkout (PYTHONPATH=src, not installed)
    __version__ = "0.0.0+unknown"
