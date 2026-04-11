"""Генерация текста комментария: Yandex Foundation Models или DeepSeek API."""

from __future__ import annotations

from pathlib import Path

import config
import deepseek_gpt
import yandex_gpt

# Если нет YANDEX_SYSTEM_PROMPT и нет файла prompts/b17_comment_system.txt
SYSTEM_PROMPT_DEFAULT = (
    "Ты пишешь комментарии на b17.ru в стиле живого обсуждения. "
    "Строго не больше трёх предложений. По существу поста, на русском. "
    "Только текст комментария, без преамбулы."
)


def _resolve_system_prompt(explicit: str | None) -> str:
    if explicit:
        return explicit
    if config.LLM_SYSTEM_PROMPT:
        return config.LLM_SYSTEM_PROMPT
    path = Path(__file__).resolve().parent / "prompts" / "b17_comment_system.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return SYSTEM_PROMPT_DEFAULT


def build_messages(
    post_title: str,
    post_body: str,
    *,
    system_prompt: str | None = None,
) -> list[dict[str, str]]:
    """Сообщения в формате Yandex API: role + text."""
    sys = _resolve_system_prompt(system_prompt)
    user = (
        "Ниже заголовок и текст публикации. Напиши один комментарий как участник обсуждения.\n\n"
        f"Заголовок:\n{post_title}\n\n"
        f"Текст поста:\n{post_body}"
    )
    return [
        {"role": "system", "text": sys},
        {"role": "user", "text": user},
    ]


def generate_comment_text(
    post_title: str,
    post_body: str,
    *,
    system_prompt: str | None = None,
) -> str:
    """
    Возвращает текст комментария.
    Если ключи провайдера не заданы — заглушка (режим разработки).

    Промпт: аргумент system_prompt, LLM_SYSTEM_PROMPT / YANDEX_SYSTEM_PROMPT в .env,
    или файл prompts/b17_comment_system.txt, или SYSTEM_PROMPT_DEFAULT в коде.
    """
    messages = build_messages(post_title, post_body, system_prompt=system_prompt)

    if config.DRY_RUN_LLM:
        hint = (
            "Задай DEEPSEEK_API_KEY и LLM_PROVIDER=deepseek"
            if config.LLM_PROVIDER == "deepseek"
            else "Задай YANDEX_API_KEY и YANDEX_FOLDER_ID"
        )
        return (
            f"[DRY_RUN] Нет ключей LLM ({hint}).\n\n"
            f"Пост: {post_title[:80]}{'…' if len(post_title) > 80 else ''}"
        )

    if config.LLM_PROVIDER == "deepseek":
        return deepseek_gpt.complete(messages, temperature=0.65, max_tokens=320)
    return yandex_gpt.complete(messages, temperature=0.65, max_tokens=320)
