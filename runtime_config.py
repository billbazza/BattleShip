"""Runtime configuration loader with macOS Keychain support.

This vault now reads operator config and secrets from the macOS Keychain first,
while still allowing process environment overrides for tests and one-off runs.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from functools import lru_cache

log = logging.getLogger("battleship.runtime_config")

KEYCHAIN_SERVICE_ENV = "BATTLESHIP_KEYCHAIN_SERVICE"
DEFAULT_KEYCHAIN_SERVICE = "polymarket-scanner"

CONFIG_NAMES = {
    "BEEHIIV_API_KEY",
    "BEEHIIV_PUBLICATION_ID",
    "BRAIN_OPENAI_COMPLEX_MODEL",
    "BRAIN_OPENAI_MODEL",
    "BRAIN_PROVIDER",
    "BRAIN_XAI_COMPLEX_MODEL",
    "BRAIN_XAI_MODEL",
    "FB_AD_ACCOUNT_ID",
    "FB_PAGE_ACCESS_TOKEN",
    "FB_PAGE_ID",
    "FB_SYSTEM_TOKEN",
    "FB_USER_TOKEN",
    "GSHEETS_CREDS",
    "GSHEETS_ID",
    "IG_USER_ID",
    "IMAP_HOST",
    "IMAP_PASS",
    "IMAP_USER",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "SMTP_HOST",
    "SMTP_PASS",
    "SMTP_USER",
    "SNAPSHOT_ALLOW_REMOTE",
    "SNAPSHOT_SECRET",
    "STRIPE_KEY",
    "STRIPE_PHASE2_LINK",
    "TALLY_WEBHOOK_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TYPEFORM_KEY",
    "XAI_API_KEY",
    "XAI_BASE_URL",
}


def keychain_service_name() -> str:
    override = os.environ.get(KEYCHAIN_SERVICE_ENV)
    if override is None:
        return DEFAULT_KEYCHAIN_SERVICE
    normalized = override.strip()
    return normalized or DEFAULT_KEYCHAIN_SERVICE


def _security_cli_available() -> bool:
    return shutil.which("security") is not None


def _keychain_supported() -> bool:
    return platform.system() == "Darwin" and _security_cli_available()


@lru_cache(maxsize=None)
def _find_keychain_value(service: str, name: str) -> str | None:
    if not _keychain_supported():
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service, "-a", name],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - host specific
        log.debug("Keychain lookup failed for %s/%s: %s", service, name, exc)
        return None

    if result.returncode != 0:
        stderr = (result.stderr or "").strip().lower()
        if "could not be found" not in stderr:
            log.debug(
                "Keychain lookup rc=%s for %s/%s: %s",
                result.returncode,
                service,
                name,
                (result.stderr or "").strip(),
            )
        return None

    return (result.stdout or "").strip()


def clear_cache() -> None:
    _find_keychain_value.cache_clear()


def get_raw(name: str, default: str | None = None, overrides: dict | None = None) -> str | None:
    if overrides and overrides.get(name) is not None:
        return str(overrides.get(name))

    env_value = os.environ.get(name)
    if env_value is not None:
        return env_value

    value = _find_keychain_value(keychain_service_name(), name)
    if value not in (None, ""):
        return value
    return default


def get(name: str, default: str = "", overrides: dict | None = None) -> str:
    value = get_raw(name, default=default, overrides=overrides)
    if value is None:
        return default
    return str(value).strip()


def get_bool(name: str, default: bool = False, overrides: dict | None = None) -> bool:
    raw = get_raw(name, overrides=overrides)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def export(names: list[str] | tuple[str, ...] | set[str] | None = None, overrides: dict | None = None) -> dict[str, str]:
    selected = sorted(names or CONFIG_NAMES)
    values: dict[str, str] = {}
    for name in selected:
        value = get(name, overrides=overrides)
        if value:
            values[name] = value
    return values
