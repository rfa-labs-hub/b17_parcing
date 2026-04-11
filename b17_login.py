"""
Вход на b17 через Playwright; сохранение сессии в b17_storage_state.json.

Надёжный способ «своего» Chrome: сначала отладка, потом скрипт (обходит падение Chrome от Playwright).

  1) Закрой все окна Chrome.
  2) Запусти chrome_start_debug.bat
  3) python b17_login.py --chrome-cdp

Без DevTools (если политика блокирует отладку) — просто Chrome + профиль + URL:

  python b17_login.py --open-chrome

Старый режим (может падать с TargetClosedError / exit 21):

  python b17_login.py --chrome-profile

  pip install -r requirements.txt
  playwright install chromium
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright

import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
STORAGE_STATE = ROOT / "b17_storage_state.json"


def _login_page_url() -> str:
    if config.B17_LOGIN_URL:
        return config.B17_LOGIN_URL
    if not config.B17_BASE_URL:
        raise ValueError("Задайте B17_BASE_URL или полный B17_LOGIN_URL в .env")
    base = config.B17_BASE_URL.rstrip("/")
    path = config.B17_LOGIN_PATH if config.B17_LOGIN_PATH.startswith("/") else f"/{config.B17_LOGIN_PATH}"
    return f"{base}{path}"


def _pause_terminal(message: str) -> None:
    sys.stdout.write("\n" + message + "\n")
    sys.stdout.flush()
    input(">>> Нажми Enter здесь, в терминале, когда будешь готов… ")


def _save_storage(context) -> None:
    context.storage_state(path=str(STORAGE_STATE))
    logger.info("Сессия сохранена: %s", STORAGE_STATE)


def run_auto(*, headed: bool) -> int:
    if not config.B17_LOGIN or not config.B17_PASSWORD:
        logger.error("В .env нужны B17_LOGIN и B17_PASSWORD.")
        return 1
    url = _login_page_url()
    logger.info("Страница входа: %s", url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            page.locator(config.B17_CSS_LOGIN).first.fill(config.B17_LOGIN)
            page.locator(config.B17_CSS_PASSWORD).first.fill(config.B17_PASSWORD)
            page.locator(config.B17_CSS_SUBMIT).first.click()
            page.wait_for_load_state("networkidle", timeout=120_000)
        except Exception as e:
            logger.exception("Ошибка входа: %s", e)
            if not headed:
                logger.info("С капчей попробуй: python b17_login.py --wait-captcha")
            browser.close()
            return 1

        _save_storage(context)
        browser.close()

    return 0


def run_wait_captcha() -> int:
    """Открыть окно, дать решить капчу, потом ввести логин/пароль из скрипта."""
    if not config.B17_LOGIN or not config.B17_PASSWORD:
        logger.error("В .env нужны B17_LOGIN и B17_PASSWORD.")
        return 1
    url = _login_page_url()
    logger.info("Страница входа: %s", url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)

        _pause_terminal(
            "В окне браузера реши капчу. Когда появятся поля входа (или страница перестанет блокировать ввод) — "
            "вернись сюда."
        )

        try:
            page.locator(config.B17_CSS_LOGIN).first.fill(config.B17_LOGIN)
            page.locator(config.B17_CSS_PASSWORD).first.fill(config.B17_PASSWORD)
            page.locator(config.B17_CSS_SUBMIT).first.click()
            page.wait_for_load_state("networkidle", timeout=120_000)
        except Exception as e:
            logger.exception("Ошибка после паузы: %s", e)
            browser.close()
            return 1

        _save_storage(context)
        browser.close()

    return 0


def run_manual() -> int:
    """Только браузер: капчу и логин делаешь руками; Enter в терминале = сохранить куки."""
    url = _login_page_url()
    logger.info("Открываю: %s", url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)

        _pause_terminal(
            "Войди на сайт полностью вручную: капча, логин, пароль — всё в окне браузера. "
            "Когда уже будешь залогинен (видна лента/профиль и т.д.) — вернись сюда."
        )

        _save_storage(context)
        browser.close()

    return 0


def _cdp_check_urls(cdp_url: str) -> list[str]:
    """Несколько URL на случай различий localhost / кастомного хоста."""
    base = cdp_url.rstrip("/")
    u = urlparse(base if "://" in base else f"http://{base}")
    port = u.port or 9222
    scheme = u.scheme or "http"
    hosts: list[str] = []
    if u.hostname:
        hosts.append(u.hostname)
    for h in ("127.0.0.1", "localhost"):
        if h not in hosts:
            hosts.append(h)
    seen: set[str] = set()
    out: list[str] = []
    for h in hosts:
        key = f"{h}:{port}"
        if key in seen:
            continue
        seen.add(key)
        out.append(f"{scheme}://{h}:{port}/json/version")
    # Иногда Chrome слушает только на ::1
    key6 = f"[::1]:{port}"
    if key6 not in seen:
        seen.add(key6)
        out.append(f"{scheme}://[::1]:{port}/json/version")
    return out


def _wait_cdp_http(cdp_url: str, max_seconds: int = 90) -> bool:
    """Ждём, пока Chrome реально поднимет HTTP-отладку (иначе ECONNREFUSED)."""
    # Важно: HTTP_PROXY/HTTPS_PROXY из среды отправляют даже 127.0.0.1 на прокси — DevTools «не отвечает».
    if any(os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY")):
        print(
            ">>> Proxy env vars detected — using trust_env=False so localhost is not proxied.",
            flush=True,
        )
    checks = _cdp_check_urls(cdp_url)
    for i in range(max_seconds):
        for check in checks:
            try:
                r = httpx.get(check, timeout=2.0, trust_env=False)
                if r.status_code == 200 and "Browser" in r.text:
                    if i > 0:
                        logger.info("Отладка поднялась через %s с (endpoint %s)", i, check)
                    return True
            except Exception:
                pass
        if i == 0 or (i + 1) % 5 == 0:
            print(
                f">>> Still waiting for DevTools HTTP ({i + 1}s / {max_seconds}s). First try: {checks[0]!r}",
                flush=True,
            )
        time.sleep(1)
    return False


def _devtools_active_port_paths(user_data: str, profile: str) -> list[str]:
    return [
        os.path.join(user_data, profile, "DevToolsActivePort"),
        os.path.join(user_data, "DevToolsActivePort"),
    ]


def _read_devtools_port_from_file(paths: list[str]) -> int | None:
    """Chrome пишет номер порта в первую строку DevToolsActivePort."""
    for p in paths:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                line = f.readline().strip()
            if line.isdigit():
                return int(line)
            if line:
                print(f">>> DevToolsActivePort unexpected first line (not a port): {line!r}", flush=True)
        except OSError:
            continue
    return None


def _wait_devtools_port_file(user_data: str, profile: str, max_wait: int = 90) -> int | None:
    """Ждём появления DevToolsActivePort (порт 0 в командной строке — Chrome сам выбирает порт)."""
    paths = _devtools_active_port_paths(user_data, profile)
    print(f">>> Looking for DevToolsActivePort under profile (up to {max_wait}s)...", flush=True)
    for i in range(max_wait):
        port = _read_devtools_port_from_file(paths)
        if port is not None:
            print(f">>> Found DevToolsActivePort -> port {port}", flush=True)
            return port
        if i > 0 and i % 10 == 0:
            print(f">>> Still no DevToolsActivePort ({i}s). Checked:", flush=True)
            for p in paths:
                print(f"     {p}", flush=True)
        time.sleep(1)
    print(">>> DevToolsActivePort never appeared — remote debugging may be blocked by policy.", flush=True)
    for p in paths:
        print(f"     {p}", flush=True)
    return None


def _find_chrome_exe() -> str | None:
    if sys.platform != "win32":
        return None
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    return next((p for p in candidates if p and os.path.isfile(p)), None)


def run_open_chrome_only() -> int:
    """
    Обычный запуск Chrome с твоим User Data и URL из .env — без remote debugging, без Playwright.
    Подходит, если политика/ПК не создают DevToolsActivePort, но браузер с профилем тебе нужен (как твой скрипт на Авито).
    Файл b17_storage_state.json не создаётся.
    """
    if sys.platform != "win32":
        logger.error("--open-chrome пока только для Windows.")
        return 1
    chrome = _find_chrome_exe()
    if not chrome:
        logger.error("chrome.exe не найден по стандартным путям.")
        return 1
    url = _login_page_url()
    user_data = config.B17_CHROME_USER_DATA_DIR
    profile = config.B17_CHROME_PROFILE_DIR
    args = [
        chrome,
        f"--user-data-dir={user_data}",
        f"--profile-directory={profile}",
        url,
    ]
    print(f">>> Launching Chrome (no CDP / no DevTools): {chrome}", flush=True)
    print(f">>> Opening URL: {url}", flush=True)
    try:
        subprocess.Popen(args, close_fds=True)
    except OSError as e:
        logger.error("Не удалось запустить Chrome: %s", e)
        return 1
    print(
        ">>> Готово. Войди на сайте в открывшемся окне. "
        "Этот режим не пишет b17_storage_state.json — только открывает браузер с профилем.",
        flush=True,
    )
    return 0


def _launch_chrome_with_debug() -> bool:
    """Windows: запуск Chrome с remote debugging. Порт 0 — реальный порт читаем из DevToolsActivePort."""
    if sys.platform != "win32":
        logger.error("--launch-chrome пока только для Windows.")
        return False
    chrome = _find_chrome_exe()
    if not chrome:
        logger.error("chrome.exe не найден по стандартным путям.")
        return False
    user_data = config.B17_CHROME_USER_DATA_DIR
    profile = config.B17_CHROME_PROFILE_DIR
    # Порт 0: Chrome выбирает свободный порт и записывает в DevToolsActivePort (надёжнее фиксированного 9222).
    args = [
        chrome,
        "--remote-debugging-port=0",
        "--remote-allow-origins=*",
        f"--user-data-dir={user_data}",
        f"--profile-directory={profile}",
    ]
    print(f">>> Closing existing chrome.exe, then starting: {chrome!r}", flush=True)
    subprocess.run(
        ["taskkill", "/F", "/IM", "chrome.exe"],
        capture_output=True,
        check=False,
    )
    time.sleep(2)
    try:
        subprocess.Popen(
            args,
            close_fds=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
    except OSError as e:
        logger.error("Не удалось запустить Chrome: %s", e)
        return False

    print(
        ">>> Chrome started with --remote-debugging-port=0 (port will be read from DevToolsActivePort).",
        flush=True,
    )
    time.sleep(2)
    return True


def run_chrome_cdp(cdp_url: str, *, launch_chrome: bool = False) -> int:
    """Подключение к уже запущенному Chrome с remote debugging (порт 9222)."""
    effective_cdp = cdp_url
    if launch_chrome:
        if not _launch_chrome_with_debug():
            return 1
        discovered = _wait_devtools_port_file(config.B17_CHROME_USER_DATA_DIR, config.B17_CHROME_PROFILE_DIR)
        if discovered is not None:
            effective_cdp = f"http://127.0.0.1:{discovered}"
        else:
            print(
                ">>> Falling back to B17_CHROME_CDP_URL / 9222 (file missing — debugging may still fail).",
                flush=True,
            )

    url = _login_page_url()
    print(f">>> CDP URL: {effective_cdp}", flush=True)
    print(f">>> Page from .env (opened ONLY after CDP works): {url}", flush=True)
    if config.B17_LOGIN_URL:
        print("    (using B17_LOGIN_URL)", flush=True)
    else:
        print(f"    (using B17_BASE_URL + path; B17_LOGIN_PATH={config.B17_LOGIN_PATH!r})", flush=True)
    print(
        ">>> Step 1/2: Chrome must answer DevTools HTTP (json/version). "
        "Step 2/2: then the script opens the page above.",
        flush=True,
    )
    logger.info("CDP: %s", effective_cdp)
    logger.info("Цель навигации: %s", url)

    print(
        ">>> Waiting for DevTools HTTP (up to 90s). Until this succeeds, your link is NOT opened.",
        flush=True,
    )
    if not _wait_cdp_http(effective_cdp):
        logger.error(
            "Порт отладки не отвечает (ECONNREFUSED). Запусти chrome_start_debug.bat и дождись строки "
            "«OK: отладка…». Не открывай Chrome из меню Пуск — только через bat."
        )
        return 1

    print(">>> CDP HTTP OK. Connecting Playwright...", flush=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(effective_cdp, timeout=120_000)
            if not browser.contexts:
                logger.error("Нет контекста браузера. Запусти chrome_start_debug.bat и закрой лишний Chrome.")
                return 1
            context = browser.contexts[0]
            # Новая вкладка даёт «пустой таб» и путает: лучше грузить URL в уже открытой вкладке.
            if context.pages:
                page = context.pages[0]
                print(f">>> Using existing tab (already {len(context.pages)} tab(s)).", flush=True)
            else:
                page = context.new_page()
                print(">>> Opened a new tab (no tabs in profile).", flush=True)

            print(f">>> Navigating to {url!r} ...", flush=True)
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            try:
                title = page.title()
            except Exception:
                title = "?"
            print(f">>> Page loaded. title={title!r} url={page.url!r}", flush=True)

            _pause_terminal(
                "В Chrome залогинься на b17 при необходимости. Потом вернись в ЭТОТ терминал и нажми Enter — "
                "сохраним куки в b17_storage_state.json."
            )

            _save_storage(context)
            browser.close()
    except Exception as e:
        logger.exception("Не удалось подключиться к Chrome: %s", e)
        logger.info(
            "Chrome с отладкой должен быть запущен через chrome_start_debug.bat, пока идёт этот скрипт."
        )
        return 1

    return 0


def run_chrome_profile() -> int:
    """Запуск Chrome с профилем через Playwright (на части ПК падает — тогда только --chrome-cdp)."""
    url = _login_page_url()
    user_data = config.B17_CHROME_USER_DATA_DIR
    profile = config.B17_CHROME_PROFILE_DIR

    logger.info("Каталог User Data: %s", user_data)
    logger.info("Профиль: %s", profile)
    logger.warning("Закрой ВСЕ окна Chrome перед запуском.")
    logger.info("Открываю страницу: %s", url)

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data,
                channel="chrome",
                headless=False,
                args=[f"--profile-directory={profile}"],
                no_viewport=True,
                ignore_default_args=config.IGNORE_DEFAULT_ARGS_FOR_SYSTEM_CHROME,
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)

            _pause_terminal(
                "Работай в открытом окне Chrome. Когда закончишь — Enter, сохраним куки в b17_storage_state.json."
            )

            _save_storage(context)
            context.close()
    except Exception as e:
        logger.exception("Chrome так не запустился: %s", e)
        logger.info(
            "Используй режим CDP: 1) закрой Chrome 2) chrome_start_debug.bat 3) python b17_login.py --chrome-cdp"
        )
        return 1

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Вход на b17 и сохранение сессии")
    g = ap.add_mutually_exclusive_group()
    g.add_argument(
        "--wait-captcha",
        action="store_true",
        help="Пауза: сначала решаешь капчу в браузере, Enter в терминале — потом скрипт вводит логин/пароль из .env",
    )
    g.add_argument(
        "--manual",
        action="store_true",
        help="Всё вручную в браузере (капча+логин), Enter в терминале — только сохранить куки",
    )
    g.add_argument(
        "--chrome-profile",
        action="store_true",
        help="Playwright запускает Chrome с твоим профилем (может падать — см. --chrome-cdp)",
    )
    g.add_argument(
        "--chrome-cdp",
        action="store_true",
        help="Подключиться к уже запущенному Chrome (chrome_start_debug.bat, порт 9222)",
    )
    g.add_argument(
        "--open-chrome",
        action="store_true",
        help="Только открыть Chrome с профилем и URL из .env — без CDP/DevTools (сессия как у обычного ярлыка)",
    )
    ap.add_argument(
        "--headed",
        action="store_true",
        help="Обычный авто-вход с видимым окном (без паузы на капчу)",
    )
    ap.add_argument(
        "--cdp-url",
        default=None,
        metavar="URL",
        help=f"URL для CDP (по умолчанию из .env: {config.B17_CHROME_CDP_URL})",
    )
    ap.add_argument(
        "--launch-chrome",
        action="store_true",
        help="Вместе с --chrome-cdp: сам завершить Chrome и поднять его с remote debugging (Windows)",
    )
    args = ap.parse_args()

    if args.open_chrome:
        return run_open_chrome_only()
    if args.chrome_cdp:
        cdp = args.cdp_url or config.B17_CHROME_CDP_URL
        return run_chrome_cdp(cdp, launch_chrome=args.launch_chrome)
    if args.chrome_profile:
        return run_chrome_profile()
    if args.manual:
        return run_manual()
    if args.wait_captcha:
        return run_wait_captcha()
    return run_auto(headed=args.headed)


if __name__ == "__main__":
    sys.exit(main())
