"""
Точка входа: сгенерировать комментарий (LLM) и при необходимости «отправить» на b17.

Пример:
  python main.py --title "Тема" --body "Текст поста..."
  python main.py --title "Тема" --body "..." --post-id 12345
"""

from __future__ import annotations

import argparse
import logging
import sys

import b17_client
import config
import llm

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    p = argparse.ArgumentParser(description="Генерация комментария для b17 (Yandex GPT или DeepSeek)")
    p.add_argument("--title", default="Тестовый пост", help="Заголовок поста")
    p.add_argument("--body", default="Содержимое поста для теста.", help="Текст поста")
    p.add_argument(
        "--post-id",
        default="",
        help="ID поста на b17 (для будущей отправки комментария)",
    )
    p.add_argument("--no-send", action="store_true", help="Только сгенерировать текст, не вызывать b17_client")
    args = p.parse_args()

    if config.DRY_RUN_LLM:
        logger.warning(
            "Режим без LLM API: ответ будет заглушкой. "
            "Yandex: YANDEX_API_KEY + YANDEX_FOLDER_ID; DeepSeek: LLM_PROVIDER=deepseek + DEEPSEEK_API_KEY."
        )

    text = llm.generate_comment_text(args.title, args.body)
    print("\n--- Текст комментария ---\n")
    print(text)
    print()

    if args.no_send or not args.post_id:
        if not args.no_send and not args.post_id:
            logger.info("Укажите --post-id для попытки отправки на b17 (или --no-send).")
        return 0

    result = b17_client.post_comment(args.post_id, text)
    logger.info("Результат b17: %s", result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
