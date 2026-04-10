"""Shared LLM wrapper for Battleship.

Uses the same macOS Keychain-backed OpenAI/xAI credentials as the
polymarket-scanner vault. Environment variables still work as temporary
overrides for tests and one-off local runs.
"""

from __future__ import annotations

import logging

from openai import OpenAI

import runtime_config

log = logging.getLogger("battleship.llm")

PROVIDER_OPENAI = "openai"
PROVIDER_XAI = "xai"
PROVIDER_AUTO = "auto"

DEFAULT_MODELS = {
    "default": {
        PROVIDER_OPENAI: "gpt-5-mini",
        PROVIDER_XAI: "grok-4.20-beta-latest-non-reasoning",
    },
    "complex": {
        PROVIDER_OPENAI: "gpt-5",
        PROVIDER_XAI: "grok-4.20-beta-latest-reasoning",
    },
}

XAI_DEFAULT_BASE_URL = "https://api.x.ai/v1"
_LAST_PROVIDER: str | None = None


def _configured_provider(provider: str, overrides: dict | None = None) -> bool:
    if provider == PROVIDER_OPENAI:
        return bool(runtime_config.get("OPENAI_API_KEY", overrides=overrides))
    if provider == PROVIDER_XAI:
        return bool(runtime_config.get("XAI_API_KEY", overrides=overrides))
    return False


def provider_order(overrides: dict | None = None) -> list[str]:
    preferred = (runtime_config.get("BRAIN_PROVIDER", "auto", overrides=overrides) or "auto").lower()
    if preferred == PROVIDER_OPENAI:
        order = [PROVIDER_OPENAI, PROVIDER_XAI]
    elif preferred == PROVIDER_XAI:
        order = [PROVIDER_XAI, PROVIDER_OPENAI]
    else:
        order = [PROVIDER_OPENAI, PROVIDER_XAI]
    return [provider for provider in order if _configured_provider(provider, overrides=overrides)]


def _default_model(provider: str, complexity: str, overrides: dict | None = None) -> str:
    bucket = "complex" if complexity == "complex" else "default"
    if provider == PROVIDER_OPENAI:
        key = "BRAIN_OPENAI_COMPLEX_MODEL" if bucket == "complex" else "BRAIN_OPENAI_MODEL"
        return runtime_config.get(key, DEFAULT_MODELS[bucket][provider], overrides=overrides)
    key = "BRAIN_XAI_COMPLEX_MODEL" if bucket == "complex" else "BRAIN_XAI_MODEL"
    return runtime_config.get(key, DEFAULT_MODELS[bucket][provider], overrides=overrides)


def _client_for_provider(provider: str, overrides: dict | None = None) -> OpenAI:
    if provider == PROVIDER_OPENAI:
        kwargs = {"api_key": runtime_config.get("OPENAI_API_KEY", overrides=overrides)}
        base_url = runtime_config.get("OPENAI_BASE_URL", overrides=overrides)
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)

    return OpenAI(
        api_key=runtime_config.get("XAI_API_KEY", overrides=overrides),
        base_url=runtime_config.get("XAI_BASE_URL", XAI_DEFAULT_BASE_URL, overrides=overrides),
    )


def availability(overrides: dict | None = None) -> dict:
    order = provider_order(overrides=overrides)
    return {
        "configured_order": order,
        "active_provider": _LAST_PROVIDER or (order[0] if order else None),
        "providers": {
            PROVIDER_OPENAI: {
                "configured": _configured_provider(PROVIDER_OPENAI, overrides=overrides),
                "model": _default_model(PROVIDER_OPENAI, "default", overrides=overrides),
            },
            PROVIDER_XAI: {
                "configured": _configured_provider(PROVIDER_XAI, overrides=overrides),
                "model": _default_model(PROVIDER_XAI, "default", overrides=overrides),
            },
        },
    }


def generate_text(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 1024,
    model: str | None = None,
    complexity: str = "default",
    temperature: float | None = None,
    overrides: dict | None = None,
) -> str:
    global _LAST_PROVIDER

    errors: list[str] = []
    for provider in provider_order(overrides=overrides):
        try:
            client = _client_for_provider(provider, overrides=overrides)
            resolved_model = model or _default_model(provider, complexity, overrides=overrides)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            kwargs = {
                "model": resolved_model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature

            response = client.chat.completions.create(**kwargs)
            text = ((response.choices or [None])[0].message.content or "").strip()
            if not text:
                raise RuntimeError(f"{provider} returned empty content")
            _LAST_PROVIDER = provider
            return text
        except Exception as exc:  # pragma: no cover - exercised in live runtime
            log.warning("LLM provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    raise RuntimeError("No configured LLM provider succeeded" + (f" ({'; '.join(errors)})" if errors else ""))
