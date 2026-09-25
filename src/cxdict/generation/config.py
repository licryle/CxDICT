"""LLM provider configuration, loaded from a `.env` file (Phase 5).

The generation pipeline talks to any OpenAI-compatible chat-completions
endpoint (e.g. LM Studio). Copy `.env.example` to `.env` and set values:

    LLM_API_ENDPOINT=http://192.168.2.147:1234/v1/chat/completions
    LLM_MODEL_NAME=qwen/qwen2.5-vl-7b
    # LLM_API_KEY=sk-...  (optional: bearer token for providers that need auth)

`.env` is gitignored (local machine configuration); `.env.example` is the
committed template. Plain process environment variables take precedence
over the `.env` file. Only the Python standard library is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    """Raised when the LLM configuration is missing or invalid."""


REQUIRED_VARS = ("LLM_API_ENDPOINT", "LLM_MODEL_NAME")

DEFAULT_BATCH_SIZE = 10
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class LLMConfig:
    """Validated provider configuration."""

    endpoint: str       # Full chat-completions URL (OpenAI-compatible API)
    model: str          # Model name as served by the endpoint
    batch_size: int = DEFAULT_BATCH_SIZE   # entries per request
    max_retries: int = DEFAULT_MAX_RETRIES  # retries per batch on failure
    timeout_s: float = DEFAULT_TIMEOUT_S    # HTTP timeout per request
    api_key: str | None = None  # optional bearer token (Authorization header)


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `.env` file content into a dict (KEY=VALUE per line)."""
    values: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f".env line {lineno}: expected KEY=VALUE")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            raise ConfigError(f".env line {lineno}: empty variable name")
        values[key] = value
    return values


def _get_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None or raw == "":
        return default
    try:
        number = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if number <= 0:
        raise ConfigError(f"{name} must be positive, got {raw!r}")
    return number


def _get_float(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name)
    if raw is None or raw == "":
        return default
    try:
        number = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if number <= 0:
        raise ConfigError(f"{name} must be positive, got {raw!r}")
    return number


def load_config(
    env_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> LLMConfig:
    """Build an LLMConfig from a `.env` file and/or environment variables.

    Process environment takes precedence over the file. Raises ConfigError
    naming any missing or invalid value.
    """
    import os

    values: dict[str, str] = {}
    if env_path is not None:
        path = Path(env_path)
        if not path.exists():
            raise ConfigError(f".env file not found: {path}")
        values.update(parse_dotenv(path.read_text(encoding="utf-8")))
    values.update(dict(os.environ if environ is None else environ))

    missing = [name for name in REQUIRED_VARS if not values.get(name)]
    if missing:
        raise ConfigError(
            f"missing required LLM configuration: {', '.join(missing)} "
            f"(set in .env or environment)"
        )
    endpoint = values["LLM_API_ENDPOINT"].strip()
    if not endpoint.startswith(("http://", "https://")):
        raise ConfigError(
            f"LLM_API_ENDPOINT must be an http(s) URL, got {endpoint!r}"
        )
    return LLMConfig(
        endpoint=endpoint,
        model=values["LLM_MODEL_NAME"].strip(),
        batch_size=_get_int(values, "LLM_BATCH_SIZE", DEFAULT_BATCH_SIZE),
        max_retries=_get_int(values, "LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES),
        timeout_s=_get_float(values, "LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S),
        api_key=(values.get("LLM_API_KEY") or "").strip() or None,
    )
