"""Вызов DeepSeek Chat API (формат совместим с OpenAI)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)


def _yandex_messages_to_openai(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """role + text (как в Yandex) → role + content (OpenAI / DeepSeek)."""
    out: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role") or "user"
        text = m.get("text") or m.get("content") or ""
        out.append({"role": role, "content": text})
    return out


def complete(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.65,
    max_tokens: int = 320,
) -> str:
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY не задан")

    url = f"{config.DEEPSEEK_BASE_URL}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": config.DEEPSEEK_MODEL,
        "messages": _yandex_messages_to_openai(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=120.0, trust_env=False) as client:
        r = client.post(url, json=payload, headers=headers)

    if r.status_code == 401:
        logger.error("DeepSeek API 401: %s", r.text)
        logger.error(
            "Проверь DEEPSEEK_API_KEY в .env (https://platform.deepseek.com/). "
            "Ключ должен быть действующим и с положительным балансом."
        )
        r.raise_for_status()

    if r.status_code >= 400:
        logger.error("DeepSeek API %s: %s", r.status_code, r.text)
        r.raise_for_status()

    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"Неожиданный ответ DeepSeek: нет choices: {data!r}")
    msg = choices[0].get("message") or {}
    text = msg.get("content")
    if not text:
        raise RuntimeError(f"Пустой ответ DeepSeek: {data!r}")
    return str(text).strip()
