"""Загрузка настроек из переменных окружения и .env."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


def _default_chrome_user_data_dir() -> str:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return str(Path(local) / "Google" / "Chrome" / "User Data")
        return str(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data")
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Application Support" / "Google" / "Chrome")
    return str(Path.home() / ".config" / "google-chrome")


def _strip(s: str | None) -> str | None:
    if s is None:
        return None
    t = s.strip()
    return t if t else None


def _env_bool(name: str, default: bool = False) -> bool:
    v = _strip(os.getenv(name))
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


# Yandex Cloud: ключ сервисного аккаунта / API-ключ и каталог (folder id)
# https://console.cloud.yandex.ru/ → каталог → ID
YANDEX_API_KEY = _strip(os.getenv("YANDEX_API_KEY"))
YANDEX_FOLDER_ID = _strip(os.getenv("YANDEX_FOLDER_ID"))

# Полный URI модели, например gpt://b1g.../yandexgpt/latest
# Если пусто — собирается из folder id (см. ниже)
YANDEX_MODEL_URI = _strip(os.getenv("YANDEX_MODEL_URI"))

YANDEX_SYSTEM_PROMPT = _strip(os.getenv("YANDEX_SYSTEM_PROMPT"))

# Генерация комментария: yandex (Foundation Models) или deepseek (API как у OpenAI)
_llm_raw = (_strip(os.getenv("LLM_PROVIDER")) or "yandex").lower()
LLM_PROVIDER = _llm_raw if _llm_raw in ("yandex", "deepseek") else "yandex"
# DeepSeek: ключ и модель — https://platform.deepseek.com/ (платный по токенам, обычно дешево; «бесплатного» API без лимитов нет)
DEEPSEEK_API_KEY = _strip(os.getenv("DEEPSEEK_API_KEY"))
DEEPSEEK_MODEL = _strip(os.getenv("DEEPSEEK_MODEL")) or "deepseek-chat"
DEEPSEEK_BASE_URL = (_strip(os.getenv("DEEPSEEK_BASE_URL")) or "https://api.deepseek.com").rstrip("/")
# Общий system prompt (LLM_SYSTEM_PROMPT перекрывает YANDEX_SYSTEM_PROMPT для любого провайдера)
LLM_SYSTEM_PROMPT = _strip(os.getenv("LLM_SYSTEM_PROMPT")) or YANDEX_SYSTEM_PROMPT

B17_BASE_URL = _strip(os.getenv("B17_BASE_URL"))
B17_AUTH_TOKEN = _strip(os.getenv("B17_AUTH_TOKEN"))

# Вход на сайт (b17_login.py)
B17_LOGIN = _strip(os.getenv("B17_LOGIN"))
B17_PASSWORD = _strip(os.getenv("B17_PASSWORD"))
# Полный URL страницы входа; если пусто — B17_BASE_URL + B17_LOGIN_PATH
B17_LOGIN_URL = _strip(os.getenv("B17_LOGIN_URL"))
B17_LOGIN_PATH = _strip(os.getenv("B17_LOGIN_PATH")) or "/login"
# CSS-селекторы полей (подправь под разметку b17 через DevTools)
B17_CSS_LOGIN = _strip(os.getenv("B17_CSS_LOGIN")) or 'input[name="login"]'
B17_CSS_PASSWORD = _strip(os.getenv("B17_CSS_PASSWORD")) or 'input[type="password"]'
B17_CSS_SUBMIT = _strip(os.getenv("B17_CSS_SUBMIT")) or 'button[type="submit"]'

# Каталог User Data Chrome и имя профиля (chrome://version → «Путь к профилю»)
B17_CHROME_USER_DATA_DIR = _strip(os.getenv("B17_CHROME_USER_DATA_DIR")) or _default_chrome_user_data_dir()
B17_CHROME_PROFILE_DIR = _strip(os.getenv("B17_CHROME_PROFILE_DIR")) or "Default"
# Подключение к уже запущенному Chrome (python b17_login.py --chrome-cdp)
B17_CHROME_CDP_URL = _strip(os.getenv("B17_CHROME_CDP_URL")) or "http://127.0.0.1:9222"

# Playwright + системный Chrome с User Data (b17_login.py, b17_comment_bot.py)
IGNORE_DEFAULT_ARGS_FOR_SYSTEM_CHROME = [
    "--disable-extensions",
    "--enable-automation",
    "--disable-sync",
]

# Бот комментариев (b17_comment_bot.py)
B17_POST_URLS = _strip(os.getenv("B17_POST_URLS"))
# Файл: по одному URL публикации на строку, строки с # — комментарии
B17_POST_URLS_FILE = _strip(os.getenv("B17_POST_URLS_FILE"))
B17_CSS_POST_TITLE = _strip(os.getenv("B17_CSS_POST_TITLE"))
B17_CSS_POST_BODY = _strip(os.getenv("B17_CSS_POST_BODY"))
B17_CSS_COMMENT_FIELD = _strip(os.getenv("B17_CSS_COMMENT_FIELD")) or "textarea"
B17_CSS_COMMENT_SUBMIT = _strip(os.getenv("B17_CSS_COMMENT_SUBMIT")) or 'button[type="submit"]'
# Пауза между комментариями (секунды). 8640 = 144 мин (~10 комментариев за сутки при равномерной паузе).
B17_DELAY_SEC = float(os.getenv("B17_DELAY_SEC") or "8640")
# Постов за один прогон (--from-feed или список URL). 0 = без лимита (все ссылки, собранные со скролла ленты).
B17_MAX_POSTS = int(os.getenv("B17_MAX_POSTS") or "0")

# Лента главной (b17_comment_bot.py --from-feed)
B17_FEED_URL = _strip(os.getenv("B17_FEED_URL")) or "https://www.b17.ru/"
B17_FEED_SCROLL_ROUNDS = int(os.getenv("B17_FEED_SCROLL_ROUNDS") or "18")
B17_FEED_SCROLL_PAUSE_SEC = float(os.getenv("B17_FEED_SCROLL_PAUSE_SEC") or "1.0")
# Regex полного URL публикации (если задан — только он решает, остальные правила ниже не используются)
B17_ARTICLE_URL_REGEX = _strip(os.getenv("B17_ARTICLE_URL_REGEX"))
# Первые сегменты пути на b17.ru для ленты (см. _article_first_segments ниже)
# Доп. префиксы пути для исключения из ленты (через запятую), например: /forum,/games
B17_FEED_EXTRA_EXCLUDE_PREFIXES = _strip(os.getenv("B17_FEED_EXTRA_EXCLUDE_PREFIXES")) or ""
# Если задан CSS-селектор — ссылки берутся только из этого блока (меньше мусора из сайдбара). Пример: main, .feed, #content
B17_FEED_LINK_CONTAINER_SELECTOR = _strip(os.getenv("B17_FEED_LINK_CONTAINER_SELECTOR"))

# Бот (b17_comment_bot.py): если системный Google Chrome не открывает сайт / about:blank
# — B17_USE_PLAYWRIGHT_CHROMIUM=1: встроенный Chromium + каталог B17_PW_LOCAL_PROFILE_DIR (логин один раз в этом окне).
# — B17_USE_STORAGE_STATE=1: браузер Playwright + куки из b17_storage_state.json (после python b17_login.py --manual и т.п.).
B17_USE_PLAYWRIGHT_CHROMIUM = _env_bool("B17_USE_PLAYWRIGHT_CHROMIUM")
B17_USE_STORAGE_STATE = _env_bool("B17_USE_STORAGE_STATE")
B17_PW_LOCAL_PROFILE_DIR = _strip(os.getenv("B17_PW_LOCAL_PROFILE_DIR")) or str(
    Path(__file__).resolve().parent / ".pw-b17-profile"
)
# Бот: подключиться к уже запущенному Chrome (chrome_start_debug.bat) — тот же профиль и вход в аккаунт Google
B17_USE_CDP = _env_bool("B17_USE_CDP")


def _article_first_segments() -> tuple[str, ...] | None:
    """None = ослабленный режим (2+ сегмента). Иначе — только перечисленные первые сегменты пути (см. b17_comment_bot._article_match)."""
    raw = os.getenv("B17_ARTICLE_PATH_FIRST_SEGMENTS")
    if raw is None:
        # Типичные публикации: https://www.b17.ru/article/871884/
        return ("article",)
    if not raw.strip():
        return None
    return tuple(s.strip().lower() for s in raw.split(",") if s.strip())


B17_ARTICLE_PATH_FIRST_SEGMENTS = _article_first_segments()


def _default_model_uri() -> str | None:
    if not YANDEX_FOLDER_ID:
        return None
    return f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest"


if not YANDEX_MODEL_URI and YANDEX_FOLDER_ID:
    YANDEX_MODEL_URI = _default_model_uri()

# Без ключей выбранного провайдера — заглушка в llm.generate_comment_text
if LLM_PROVIDER == "deepseek":
    DRY_RUN_LLM = not DEEPSEEK_API_KEY
else:
    DRY_RUN_LLM = not YANDEX_API_KEY or not YANDEX_FOLDER_ID
