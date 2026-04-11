"""
Обход публикаций b17: текст поста -> Yandex GPT -> комментарий в браузере.

Режимы:
  - Список URL: b17_post_urls.txt или B17_POST_URLS в .env
  - Лента главной: скролл https://www.b17.ru/ , сбор ссылок на публикации, затем те же шаги

Браузер:
  - по умолчанию Google Chrome + User Data;
  - --connect-cdp: подключение к уже запущенному Chrome (chrome_start_debug.bat) — тот же профиль и аккаунт Google;
  - встроенный Chromium (.pw-b17-profile) — не «ваш» Chrome; вход в Google часто «небезопасен»;
  - куки из b17_storage_state.json после b17_login.py.

На странице поста: поле с плейсхолдером про «комментарий» и кнопка «Отправить».

  playwright install chromium

Пример:
  python b17_comment_bot.py --from-feed --dry-run --max-posts 3
  python b17_comment_bot.py --from-feed --connect-cdp
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

import config
import llm
from b17_login import _wait_cdp_http

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent


def _is_blank_or_internal_start(url: str) -> bool:
    u = (url or "").strip().lower()
    return (
        not u
        or u.startswith("about:")
        or u == "chrome://newtab/"
        or "new-tab-page" in u
        or u.startswith("chrome://new-tab")
    )


def _navigate_page_to_url(page: Page, url: str) -> None:
    """Переход на URL; при «залипании» about:blank — location.replace и повтор."""
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    if not _is_blank_or_internal_start(page.url):
        return
    logger.warning("После goto URL всё ещё пустой/внутренний (%s) — пробую location.replace", page.url)
    try:
        with page.expect_navigation(timeout=120_000):
            page.evaluate("(u) => window.location.replace(u)", url)
        page.wait_for_load_state("domcontentloaded", timeout=120_000)
    except Exception as e:
        logger.warning("location.replace: %s — повторный goto", e)
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)


def _open_url_in_persistent_context(context, url: str) -> Page:
    """
    Persistent Chrome часто даёт первую вкладку about:blank или chrome://new-tab-page —
    навигация «не видна» или уходит во вторую вкладку. Поднимаем фокус, при необходимости
    открываем новую вкладку и закрываем пустую.
    """
    time.sleep(0.5)
    page: Page | None = None
    if context.pages:
        page = context.pages[0]
    else:
        page = context.new_page()
    try:
        page.bring_to_front()
    except Exception:
        pass
    try:
        _navigate_page_to_url(page, url)
    except Exception as e:
        logger.warning("Первый переход: %s", e)

    if not _is_blank_or_internal_start(page.url):
        logger.info("Открыто: %s", page.url)
        return page

    logger.info("Первая вкладка не загрузила сайт — открываю новую вкладку с тем же URL")
    page2 = context.new_page()
    try:
        page2.bring_to_front()
    except Exception:
        pass
    try:
        _navigate_page_to_url(page2, url)
    except Exception as e:
        logger.exception("Вторая вкладка: %s", e)
        raise
    for p in list(context.pages):
        if p is page2:
            continue
        if _is_blank_or_internal_start(p.url):
            try:
                p.close()
            except Exception:
                pass
    logger.info("Открыто: %s", page2.url)
    return page2


def _launch_browser(
    p,
    *,
    kill_chrome: bool,
    want_storage: bool,
    want_chromium: bool,
    connect_cdp: bool,
    cdp_url: str,
) -> tuple[Browser | None, BrowserContext]:
    """
    Системный Google Chrome с User Data часто даёт пустую вкладку или не грузит сайт.
    Встроенный Chromium — не «ваш» Chrome: без полноценной синхронизации; Google часто блокирует вход
    в аккаунт Google с пометкой «небезопасно».
    Надёжно «как обычный Chrome»: подключение по CDP к уже запущенному chrome_start_debug.bat.
    """
    storage_path = ROOT / "b17_storage_state.json"
    user_data = config.B17_CHROME_USER_DATA_DIR
    profile = config.B17_CHROME_PROFILE_DIR

    if connect_cdp:
        logger.info(
            "Режим браузера: подключение к уже запущенному Google Chrome (CDP %s). "
            "Это тот же профиль Windows, что и при ручном запуске — синхронизация и аккаунт Google.",
            cdp_url,
        )
        print(
            ">>> Должен быть запущен Chrome с отладкой (chrome_start_debug.bat), не второй экземпляр из меню Пуск.",
            flush=True,
        )
        if not _wait_cdp_http(cdp_url):
            raise RuntimeError(
                f"CDP не отвечает ({cdp_url}). Запусти chrome_start_debug.bat и дождись, пока откроется Chrome."
            )
        browser = p.chromium.connect_over_cdp(cdp_url, timeout=120_000)
        if not browser.contexts:
            raise RuntimeError("В Chrome нет контекста — открой окно через chrome_start_debug.bat.")
        return browser, browser.contexts[0]

    if want_storage and storage_path.is_file():
        logger.info("Режим браузера: Playwright Chromium + storage_state (%s)", storage_path)
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(storage_path))
        return browser, context

    if want_storage and not storage_path.is_file():
        logger.warning(
            "Запрошен storage_state, но нет файла %s — сделай вход через b17_login.py (manual/wait-captcha) "
            "или поставь B17_USE_PLAYWRIGHT_CHROMIUM=1",
            storage_path,
        )

    if want_chromium:
        Path(config.B17_PW_LOCAL_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
        logger.info(
            "Режим браузера: встроенный Chromium, отдельный профиль %s "
            "(первый раз открой в этом окне https://www.b17.ru и войди в аккаунт)",
            config.B17_PW_LOCAL_PROFILE_DIR,
        )
        context = p.chromium.launch_persistent_context(
            config.B17_PW_LOCAL_PROFILE_DIR,
            headless=False,
            no_viewport=True,
        )
        return None, context

    if sys.platform == "win32" and kill_chrome:
        logger.info("Закрываю chrome.exe, чтобы Playwright мог открыть профиль…")
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True, check=False)
        time.sleep(2)

    logger.info("Режим браузера: Google Chrome (User Data=%s, профиль=%s)", user_data, profile)
    context = p.chromium.launch_persistent_context(
        user_data,
        channel="chrome",
        headless=False,
        args=[f"--profile-directory={profile}"],
        no_viewport=True,
        ignore_default_args=config.IGNORE_DEFAULT_ARGS_FOR_SYSTEM_CHROME,
    )
    return None, context


# Ссылки на разделы сайта, не на отдельную публикацию (статьи ≠ форум и т.п.)
_EXCLUDE_PATH_PREFIXES = (
    "/login",
    "/register",
    "/search",
    "/user/",
    "/tag/",
    "/api/",
    "/static",
    "/privacy",
    "/terms",
    "/help",
    "/about",
    "/forum",  # топики форума — другая разметка, нет поля комментария как у статей
)

_article_re_compiled: re.Pattern[str] | None = None


def _exclude_path_prefixes() -> tuple[str, ...]:
    extra = (config.B17_FEED_EXTRA_EXCLUDE_PREFIXES or "").strip()
    out: list[str] = list(_EXCLUDE_PATH_PREFIXES)
    for part in extra.split(","):
        s = part.strip().lower()
        if not s:
            continue
        if not s.startswith("/"):
            s = "/" + s
        out.append(s)
    return tuple(dict.fromkeys(out))


def _describe_article_url_rule() -> str:
    if config.B17_ARTICLE_URL_REGEX:
        return "только URL, подходящие под regex (переменная B17_ARTICLE_URL_REGEX)"
    segs = config.B17_ARTICLE_PATH_FIRST_SEGMENTS
    if segs is None:
        return (
            "путь из двух и более сегментов на b17.ru (кроме forum, topic.php и пр. из исключений) — "
            "режим B17_ARTICLE_PATH_FIRST_SEGMENTS="
        )
    return (
        f"https://www.b17.ru/article/<номер>/ — первый сегмент пути один из: {', '.join(segs)}; "
        f"для «article» второй сегмент — только цифры (id). Настройка: B17_ARTICLE_PATH_FIRST_SEGMENTS"
    )


def _article_match(href: str) -> bool:
    if config.B17_ARTICLE_URL_REGEX:
        global _article_re_compiled
        if _article_re_compiled is None:
            _article_re_compiled = re.compile(config.B17_ARTICLE_URL_REGEX, re.I)
        return bool(_article_re_compiled.search(href))
    try:
        u = urlparse(href)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    host = (u.netloc or "").lower()
    if "b17.ru" not in host:
        return False
    path = (u.path or "").rstrip("/")
    if not path:
        return False
    low = path.lower()
    # Типичные URL форума вне префикса /forum (редко, но на всякий случай)
    if "topic.php" in low:
        return False
    for p in _exclude_path_prefixes():
        base = p.rstrip("/")
        if not base:
            continue
        if low == base or low.startswith(base + "/"):
            return False
    parts = [x for x in path.split("/") if x]
    if not parts:
        return False
    segs = config.B17_ARTICLE_PATH_FIRST_SEGMENTS
    if segs is not None:
        first = parts[0].lower()
        if first not in segs:
            return False
        if len(parts) < 2:
            return False
        # Как на сайте: /article/871884/ — id только цифры
        if first == "article" and not parts[1].isdigit():
            return False
        return True
    return len(parts) >= 2


def load_post_urls() -> list[str]:
    raw: list[str] = []
    if config.B17_POST_URLS:
        raw.extend(u.strip() for u in config.B17_POST_URLS.split(",") if u.strip())
    path = Path(config.B17_POST_URLS_FILE) if config.B17_POST_URLS_FILE else ROOT / "b17_post_urls.txt"
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                raw.append(line)
    seen: set[str] = set()
    out: list[str] = []
    for u in raw:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def collect_feed_urls(page: Page, stop_after: int | None = None) -> list[str]:
    """Главная: скролл вниз, сбор уникальных ссылок на публикации по порядку первого появления.

    Если задан stop_after — прекращаем скролл, как только набралось достаточно ссылок (экономия времени).
    """
    feed = config.B17_FEED_URL.rstrip("/") + "/"
    cur = page.url.split("#")[0].rstrip("/") + "/"
    if _is_blank_or_internal_start(page.url) or cur.rstrip("/") != feed.rstrip("/"):
        logger.info("Открываю ленту: %s", feed)
        try:
            _navigate_page_to_url(page, feed)
        except Exception:
            page.goto(feed, wait_until="domcontentloaded", timeout=120_000)
    else:
        logger.info("Уже на ленте: %s", feed)
    time.sleep(1.5)
    logger.info("Какие ссылки берём с ленты: %s", _describe_article_url_rule())
    seen: set[str] = set()
    order: list[str] = []
    link_root = (config.B17_FEED_LINK_CONTAINER_SELECTOR or "").strip()
    if link_root:
        logger.info("Сбор ссылок только внутри контейнера: %s", link_root)
    for r in range(config.B17_FEED_SCROLL_ROUNDS):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(config.B17_FEED_SCROLL_PAUSE_SEC)
        if link_root:
            hrefs = page.evaluate(
                """(selector) => {
                    const r = document.querySelector(selector);
                    const el = r || document.body;
                    return Array.from(el.querySelectorAll('a[href]')).map(a => a.href);
                }""",
                link_root,
            )
        else:
            hrefs = page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"""
            )
        for h in hrefs:
            h = h.split("#")[0].rstrip("/")
            if not h or h in seen:
                continue
            if not _article_match(h):
                continue
            seen.add(h)
            order.append(h)
        logger.info(
            "Скролл %s/%s: уникальных ссылок на публикации: %s",
            r + 1,
            config.B17_FEED_SCROLL_ROUNDS,
            len(order),
        )
        if stop_after and len(order) >= stop_after:
            logger.info("Достигнут лимит ссылок (%s), скролл остановлен.", stop_after)
            return order
    return order


def _extract_post(page: Page) -> tuple[str, str]:
    title_sel = config.B17_CSS_POST_TITLE or "h1"
    body_sel = config.B17_CSS_POST_BODY or "article"
    title = page.title()
    try:
        if page.locator(title_sel).count() > 0:
            title = page.locator(title_sel).first.inner_text(timeout=10_000)
    except Exception as e:
        logger.warning("Заголовок: %s", e)
    body = ""
    try:
        if page.locator(body_sel).count() > 0:
            body = page.locator(body_sel).first.inner_text(timeout=15_000)
        elif page.locator("main").count() > 0:
            body = page.locator("main").first.inner_text(timeout=10_000)
    except Exception as e:
        logger.warning("Текст поста: %s", e)
    if not body.strip():
        try:
            body = page.locator("body").inner_text(timeout=10_000)[:12000]
        except Exception:
            body = ""
    return title.strip() or "(без заголовка)", (body.strip() or "")[:12000]


def _fill_comment_field(page: Page, text: str) -> None:
    """Поле «ваш комментарий» — по плейсхолдеру / роли, иначе селектор из .env."""
    try:
        ph = page.get_by_placeholder(re.compile(r"комментарий", re.I))
        if ph.count() > 0:
            ph.first.fill(text, timeout=15_000)
            return
    except Exception:
        pass
    try:
        tb = page.get_by_role("textbox", name=re.compile(r"комментарий", re.I))
        if tb.count() > 0:
            tb.first.fill(text, timeout=15_000)
            return
    except Exception:
        pass
    page.locator(config.B17_CSS_COMMENT_FIELD).first.fill(text, timeout=15_000)


def _click_send_comment(page: Page) -> None:
    """Кнопка «Отправить» под полем."""
    try:
        btn = page.get_by_role("button", name=re.compile(r"отправить", re.I))
        if btn.count() > 0:
            btn.first.click(timeout=15_000)
            return
    except Exception:
        pass
    try:
        page.locator("button").filter(has_text=re.compile(r"отправить", re.I)).first.click(timeout=15_000)
        return
    except Exception:
        pass
    page.locator(config.B17_CSS_COMMENT_SUBMIT).first.click(timeout=15_000)


def run(
    *,
    dry_run: bool,
    max_posts: int | None,
    kill_chrome: bool,
    from_feed: bool,
    use_chromium: bool = False,
    use_storage: bool = False,
    connect_cdp: bool = False,
    cdp_url: str | None = None,
) -> int:
    urls: list[str] = []
    if not from_feed:
        urls = load_post_urls()
        if not urls:
            logger.error(
                "Нет URL. Добавь b17_post_urls.txt или B17_POST_URLS, либо запусти с --from-feed."
            )
            return 1

    limit = max_posts if max_posts is not None else config.B17_MAX_POSTS

    # Сразу открыть сайт в первой вкладке (иначе Chrome часто стартует с about:blank — «пустой браузер»).
    if from_feed:
        chrome_startup_url = config.B17_FEED_URL.rstrip("/") + "/"
    else:
        chrome_startup_url = urls[0]

    want_cdp = connect_cdp or config.B17_USE_CDP
    effective_cdp = (cdp_url or config.B17_CHROME_CDP_URL or "http://127.0.0.1:9222").rstrip("/")
    want_storage = (use_storage or config.B17_USE_STORAGE_STATE) and not want_cdp
    want_chromium = (use_chromium or config.B17_USE_PLAYWRIGHT_CHROMIUM) and not want_cdp

    browser: Browser | None = None
    with sync_playwright() as p:
        try:
            browser, context = _launch_browser(
                p,
                kill_chrome=kill_chrome and not want_cdp,
                want_storage=want_storage,
                want_chromium=want_chromium,
                connect_cdp=want_cdp,
                cdp_url=effective_cdp,
            )
        except Exception as e:
            logger.exception("Не удалось запустить браузер: %s", e)
            logger.info(
                "Если сайт не открывается: свой Google Chrome по CDP — "
                "chrome_start_debug.bat, затем python b17_comment_bot.py --from-feed --connect-cdp. "
                "Либо B17_USE_PLAYWRIGHT_CHROMIUM=1 (отдельный Chromium, не аккаунт Chrome)."
            )
            return 1

        try:
            if from_feed:
                logger.info("Открываю ленту: %s", chrome_startup_url)
                try:
                    page = _open_url_in_persistent_context(context, chrome_startup_url)
                except Exception as e:
                    logger.exception("Не удалось открыть ленту: %s", e)
                    return 1
            else:
                page = context.pages[0] if context.pages else context.new_page()
                logger.info("Первая вкладка: %s", page.url)
                if _is_blank_or_internal_start(page.url):
                    logger.info("Вкладка без URL — перехожу на %s", chrome_startup_url)
                    try:
                        page = _open_url_in_persistent_context(context, chrome_startup_url)
                    except Exception as e:
                        logger.exception("Не удалось открыть стартовую страницу: %s", e)
                        return 1

            if from_feed:
                need = limit if limit > 0 else None
                urls = collect_feed_urls(page, stop_after=need)
                if limit > 0:
                    urls = urls[:limit]
                if not urls:
                    logger.error(
                        "После скролла не найдено ссылок на публикации. "
                        "Задай B17_ARTICLE_URL_REGEX в .env или проверь, что ты залогинен на сайте."
                    )
                    return 1

            print(f">>> Постов в очереди: {len(urls)}", flush=True)
            if dry_run:
                print(">>> DRY-RUN: комментарии только в консоль, форма не отправляется.", flush=True)

            logger.info(
                "LLM-провайдер: %s (из .env LLM_PROVIDER). Для DeepSeek: LLM_PROVIDER=deepseek и DEEPSEEK_API_KEY.",
                config.LLM_PROVIDER,
            )

            for i, url in enumerate(urls, 1):
                logger.info("[%s/%s] %s", i, len(urls), url)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
                    time.sleep(1)
                    title, body = _extract_post(page)
                    comment = llm.generate_comment_text(title, body)
                    print(f"\n--- Комментарий ---\n{comment}\n", flush=True)
                    if dry_run:
                        continue
                    _fill_comment_field(page, comment)
                    _click_send_comment(page)
                    page.wait_for_load_state("domcontentloaded", timeout=60_000)
                    logger.info("Отправлено.")
                except Exception as e:
                    logger.exception("Ошибка на %s: %s", url, e)
                time.sleep(config.B17_DELAY_SEC)
        finally:
            try:
                context.close()
            except Exception:
                pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Комментирование публикаций b17 через Yandex GPT + Chrome")
    ap.add_argument("--dry-run", action="store_true", help="Только сгенерировать текст, не отправлять")
    ap.add_argument(
        "--max-posts",
        type=int,
        default=None,
        metavar="N",
        help="Сколько постов обработать (по умолчанию B17_MAX_POSTS из .env, сейчас обычно 10 для ленты)",
    )
    ap.add_argument(
        "--from-feed",
        action="store_true",
        help="Собрать ссылки со главной (скролл), затем комментировать",
    )
    ap.add_argument(
        "--no-kill-chrome",
        action="store_true",
        help="Не завершать chrome.exe перед стартом (только режим Google Chrome)",
    )
    ap.add_argument(
        "--use-chromium",
        action="store_true",
        help="Встроенный Chromium + профиль в .pw-b17-profile (если Google Chrome не грузит сайт)",
    )
    ap.add_argument(
        "--use-storage",
        action="store_true",
        help="Куки из b17_storage_state.json (после входа через b17_login.py)",
    )
    ap.add_argument(
        "--connect-cdp",
        action="store_true",
        help="Подключиться к уже запущенному Google Chrome (chrome_start_debug.bat) — твой профиль и аккаунт Google",
    )
    ap.add_argument(
        "--cdp-url",
        default=None,
        metavar="URL",
        help="Адрес CDP (по умолчанию B17_CHROME_CDP_URL, обычно http://127.0.0.1:9222)",
    )
    args = ap.parse_args()
    return run(
        dry_run=args.dry_run,
        max_posts=args.max_posts,
        kill_chrome=not args.no_kill_chrome,
        from_feed=args.from_feed,
        use_chromium=args.use_chromium,
        use_storage=args.use_storage,
        connect_cdp=args.connect_cdp,
        cdp_url=args.cdp_url,
    )


if __name__ == "__main__":
    sys.exit(main())
