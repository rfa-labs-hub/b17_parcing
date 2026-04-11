"""Вызов Yandex GPT через Foundation Models API (REST)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


def _extract_text(data: dict[str, Any]) -> str:
    """Достаёт текст ответа из JSON (обёртка result или корень)."""
    root = data.get("result", data)
    alts = root.get("alternatives") or []
    if not alts:
        raise RuntimeError(f"Неожиданный ответ API: нет alternatives: {data!r}")
    msg = alts[0].get("message") or {}
    text = msg.get("text")
    if not text:
        raise RuntimeError(f"Пустой текст в ответе: {data!r}")
    return str(text).strip()


def complete(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 500,
) -> str:
    """
    messages: список словарей с ключами role и text (формат Yandex API).
    """
    model_uri = config.YANDEX_MODEL_URI
    if not model_uri:
        raise RuntimeError("YANDEX_MODEL_URI не задан и не удалось собрать из YANDEX_FOLDER_ID")

    payload: dict[str, Any] = {
        "modelUri": model_uri,
        "completionOptions": {
            "stream": False,
            "temperature": temperature,
            "maxTokens": max_tokens,
        },
        "messages": messages,
    }

    headers = {
        "Authorization": f"Api-Key {config.YANDEX_API_KEY}",
        "x-folder-id": config.YANDEX_FOLDER_ID or "",
    }

    with httpx.Client(timeout=120.0, trust_env=False) as client:
        r = client.post(COMPLETION_URL, json=payload, headers=headers)

    if r.status_code == 401:
        logger.error("Yandex API 401: %s", r.text)
        logger.error(
            "Ключ не принят (Unknown api key / Unauthorized). Проверь: "
            "1) В консоли Yandex Cloud в том же облаке, что и каталог, создай API-ключ: "
            "https://yandex.cloud/ru/docs/iam/operations/api-key/create "
            "2) YANDEX_API_KEY — именно секретный ключ API, не OAuth и не ID ключа. "
            "3) YANDEX_FOLDER_ID — ID каталога (b1g…), в котором включён YandexGPT. "
            "4) Если ключ старый — создай новый и обнови .env"
        )
        r.raise_for_status()

    if r.status_code == 403:
        logger.error("Yandex API 403: %s", r.text)
        logger.error(
            "Нет прав на каталог/облако (Permission denied). Варианты: "
            "1) Владелец каталога должен выдать аккаунту API-ключа роль вроде "
            "`ai.languageModels.user` на этот каталог (или сервисную роль с доступом к YandexGPT). "
            "2) Проверь биллинг и квоты в каталоге. "
            "3) Перейти на DeepSeek: в .env LLM_PROVIDER=deepseek и DEEPSEEK_API_KEY=…"
        )
        r.raise_for_status()

    if r.status_code == 400 and "does not match" in r.text and "folder" in r.text.lower():
        logger.error("Yandex API 400: %s", r.text)
        logger.error(
            "YANDEX_FOLDER_ID в .env не совпадает с каталогом, к которому привязан этот API-ключ. "
            "В ответе облака: «service account folder ID» — поставь именно его в YANDEX_FOLDER_ID. "
            "Либо создай новый API-ключ в том каталоге, чей ID ты хочешь использовать. "
            "Если задан YANDEX_MODEL_URI — в нём должен быть тот же folder id в виде gpt://<тот_же_id>/yandexgpt/latest "
            "(или убери YANDEX_MODEL_URI, чтобы он собрался из YANDEX_FOLDER_ID)."
        )
        r.raise_for_status()

    if r.status_code >= 400:
        logger.error("Yandex API %s: %s", r.status_code, r.text)
        r.raise_for_status()

    data = r.json()
    return _extract_text(data)
