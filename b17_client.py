"""
Клиент для публикации комментариев на b17.

Когда появится документация/API — реализуйте post_comment под реальные эндпоинты.
Пока: заглушка, которая только логирует намерение.
"""

from __future__ import annotations

import logging

import config

logger = logging.getLogger(__name__)


def post_comment(post_id: str, text: str) -> dict:
    """
    Опубликует комментарий к посту.

    :param post_id: идентификатор поста в системе b17 (формат уточните по API)
    :param text: текст комментария
    :return: ответ сервера (заглушка — словарь с полями ok, detail)
    """
    if not config.B17_BASE_URL:
        logger.info(
            "B17_BASE_URL не задан — комментарий не отправлен (post_id=%s, len(text)=%s)",
            post_id,
            len(text),
        )
        return {
            "ok": False,
            "detail": "B17_BASE_URL не настроен; комментарий не отправлен.",
            "post_id": post_id,
        }

    # TODO: httpx.post(f"{config.B17_BASE_URL}/...", json={...}, headers=...)
    raise NotImplementedError("Реализуйте HTTP-вызов к API b17 после появления спецификации.")
