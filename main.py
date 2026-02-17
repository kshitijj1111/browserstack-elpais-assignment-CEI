import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium.common.exceptions import TimeoutException, WebDriverException

try:
    # Local convenience: auto-download chromedriver
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.service import Service as ChromeService
except Exception:
    ChromeDriverManager = None
    ChromeService = None


ELPAIS_HOME = "https://elpais.com/"
ELPAIS_OPINION = "https://elpais.com/opinion/"

OUTPUT_DIR = "outputs"
IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")


@dataclass
class Article:
    url: str
    title_es: str
    content_es: str
    image_url: Optional[str]
    image_path: Optional[str] = None
    title_en: Optional[str] = None


def safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"[\s_-]+", "_", name)
    return name[:max_len] if len(name) > max_len else name


def build_local_driver() -> webdriver.Chrome:
    """
    Local Chrome driver with Spanish language preference.
    """
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    # Force Spanish UI + content preference where possible
    chrome_options.add_argument("--lang=es-ES")
    chrome_options.add_experimental_option("prefs", {"intl.accept_languages": "es-ES,es"})

    if ChromeDriverManager is not None:
        service = ChromeService(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=chrome_options)

    # If webdriver-manager isn't available, assume chromedriver is already in PATH
    return webdriver.Chrome(options=chrome_options)


def build_browserstack_driver(capabilities: dict) -> webdriver.Remote:
    username = os.getenv("BROWSERSTACK_USERNAME", "").strip()
    access_key = os.getenv("BROWSERSTACK_ACCESS_KEY", "").strip()
    if not username or not access_key:
        raise RuntimeError("Missing BROWSERSTACK_USERNAME / BROWSERSTACK_ACCESS_KEY in environment.")

    hub_url = f"https://{username}:{access_key}@hub-cloud.browserstack.com/wd/hub"

    # Selenium 4: pass capabilities using Options
    options = webdriver.ChromeOptions()  # works for most; BrowserStack will respect caps
    for k, v in capabilities.items():
        options.set_capability(k, v)

    return webdriver.Remote(command_executor=hub_url, options=options)


def wait_for_page_ready(driver: webdriver.Remote, timeout: int = 20) -> None:
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def dismiss_consent_if_present(driver: webdriver.Remote) -> None:
    """
    El País may show cookie/consent overlays. We try a few common button patterns.
    This should not fail the run if not present.
    """
    candidates = [
        (By.XPATH, "//button[contains(., 'Aceptar') or contains(., 'ACEPTAR')]"),
        (By.XPATH, "//button[contains(., 'Aceptar y continuar')]"),
        (By.XPATH, "//button[contains(., 'Consentir')]"),
        (By.XPATH, "//button[contains(., 'Agree') or contains(., 'I agree')]"),
        (By.CSS_SELECTOR, "button#didomi-notice-agree-button"),
        (By.CSS_SELECTOR, "button[aria-label*='Aceptar']"),
    ]

    for by, sel in candidates:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, sel)))
            btn.click()
            time.sleep(1)
            return
        except Exception:
            continue


def ensure_spanish(driver: webdriver.Remote) -> None:
    """
    Ensure content is in Spanish.
    - Checks <html lang="...">.
    - If not Spanish, we force-navigate to Spanish El País (main site).
    """
    try:
        html_lang = driver.find_element(By.TAG_NAME, "html").get_attribute("lang") or ""
        if html_lang.lower().startswith("es"):
            return
    except Exception:
        pass

    # Force Spanish pages
    driver.get(ELPAIS_HOME)
    wait_for_page_ready(driver)
    dismiss_consent_if_present(driver)


def get_first_five_opinion_links(driver: webdriver.Remote) -> List[str]:
    """
    On https://elpais.com/opinion/ get first 5 article links.

    Uses resilient selector: "article h2 a" and filters unique hrefs.
    """
    driver.get(ELPAIS_OPINION)
    wait_for_page_ready(driver)
    dismiss_consent_if_present(driver)

    ensure_spanish(driver)

    # Wait for headline links to appear
    WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "article h2 a")))

    anchors = driver.find_elements(By.CSS_SELECTOR, "article h2 a")
    links: List[str] = []
    seen = set()

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append(href)
        if len(links) == 5:
            break

    return links


def extract_article_title(driver: webdriver.Remote) -> str:
    """
    Title usually in h1.
    """
    title_el = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1")))
    return (title_el.text or "").strip()


def extract_article_content(driver: webdriver.Remote) -> str:
    """
    Article body: El País often renders paragraphs inside the main <article>.
    We try a few selectors; fallback to collecting <article p>.
    """
    selectors = [
        "article p",  # broad but reliable
        "div[data-dtm-region='articulo_cuerpo'] p",
        "section[data-dtm-region='articulo_cuerpo'] p",
    ]

    paragraphs: List[str] = []
    for sel in selectors:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            for p in els:
                text = (p.text or "").strip()
                if text:
                    paragraphs.append(text)
            if len(paragraphs) >= 3:
                break

    # Clean up & join
    content = "\n".join(paragraphs).strip()
    return content


def extract_cover_image_url(driver: webdriver.Remote) -> Optional[str]:
    """
    Many articles include an og:image meta tag.
    We'll prefer that. Fallback to first figure img.
    """
    try:
        og = driver.find_elements(By.CSS_SELECTOR, "meta[property='og:image']")
        if og:
            url = og[0].get_attribute("content")
            if url:
                return url
    except Exception:
        pass

    try:
        imgs = driver.find_elements(By.CSS_SELECTOR, "article figure img")
        if imgs:
            src = imgs[0].get_attribute("src") or imgs[0].get_attribute("data-src")
            if src:
                return src
    except Exception:
        pass

    return None


def download_image(image_url: str, title_es: str) -> Optional[str]:
    """
    Downloads image to outputs/images/.
    """
    try:
        safe_mkdir(IMAGES_DIR)

        parsed = urlparse(image_url)
        ext = os.path.splitext(parsed.path)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"

        filename = sanitize_filename(title_es) or "article_image"
        path = os.path.join(IMAGES_DIR, f"{filename}{ext}")

        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(image_url, headers=headers, timeout=20)
        resp.raise_for_status()

        with open(path, "wb") as f:
            f.write(resp.content)

        return path
    except Exception:
        return None


def translate_title_to_english(title_es: str) -> str:
    """
    Uses RapidAPI Google Translate 113 API (as suggested in assignment).
    Env needed:
      RAPIDAPI_KEY
      RAPIDAPI_HOST (default: google-translate113.p.rapidapi.com)
      TRANSLATE_API_URL
    """
    api_key = os.getenv("RAPIDAPI_KEY", "").strip()
    api_host = os.getenv("RAPIDAPI_HOST", "google-translate113.p.rapidapi.com").strip()
    api_url = os.getenv("TRANSLATE_API_URL", "").strip()

    if not api_key or not api_url:
        # If missing keys, fallback to returning original (but clearly marked)
        return f"[TRANSLATION_SKIPPED_NO_API_KEY] {title_es}"

    headers = {
        "content-type": "application/json",
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": api_host,
    }
    payload = {
        "from": "es",
        "to": "en",
        "text": title_es,
    }

    resp = requests.post(api_url, json=payload, headers=headers, timeout=25)
    resp.raise_for_status()
    data = resp.json()

    # Different RapidAPI providers return different shapes.
    # We try common keys safely.
    for key_path in [
        ("trans",),
        ("translation",),
        ("translated_text",),
        ("data", "translation"),
        ("data", "translatedText"),
    ]:
        cur = data
        ok = True
        for k in key_path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and isinstance(cur, str) and cur.strip():
            return cur.strip()

    # Last fallback: stringify json
    return str(data)


def find_repeated_words_over_two(titles_en: List[str]) -> List[Tuple[str, int]]:
    """
    Identify words repeated more than twice across all translated headers combined.
    """
    joined = " ".join(titles_en).lower()
    words = re.findall(r"[a-z']+", joined)  # english word-ish tokens

    counts: Dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1

    repeated = [(w, c) for w, c in counts.items() if c > 2]
    repeated.sort(key=lambda x: (-x[1], x[0]))
    return repeated


def scrape_opinion_articles(driver: webdriver.Remote) -> List[Article]:
    links = get_first_five_opinion_links(driver)
    articles: List[Article] = []

    for idx, url in enumerate(links, start=1):
        driver.get(url)
        wait_for_page_ready(driver)
        dismiss_consent_if_present(driver)
        ensure_spanish(driver)

        title_es = extract_article_title(driver)
        content_es = extract_article_content(driver)
        image_url = extract_cover_image_url(driver)

        article = Article(url=url, title_es=title_es, content_es=content_es, image_url=image_url)

        if image_url:
            article.image_path = download_image(image_url, title_es)

        articles.append(article)

        # Small pacing (helps stability across remote + mobile)
        time.sleep(1)

    return articles


def print_articles_spanish(articles: List[Article]) -> None:
    print("\n====================")
    print("SCRAPED ARTICLES (SPANISH)")
    print("====================\n")

    for i, a in enumerate(articles, start=1):
        print(f"[{i}] URL: {a.url}")
        print(f"TITLE (ES): {a.title_es}\n")
        print("CONTENT (ES):")
        print(a.content_es if a.content_es else "[No content captured]")
        print()
        if a.image_url:
            print(f"IMAGE URL: {a.image_url}")
            print(f"SAVED TO: {a.image_path if a.image_path else '[Download failed]'}")
        else:
            print("IMAGE: [Not available]")
        print("\n" + "-" * 60 + "\n")


def print_translations(articles: List[Article]) -> None:
    print("\n====================")
    print("TRANSLATED HEADERS (ENGLISH)")
    print("====================\n")
    for i, a in enumerate(articles, start=1):
        print(f"[{i}] {a.title_en}")


def run_once(mode: str, capabilities: Optional[Dict] = None) -> List[Article]:
    driver = None
    try:
        if mode == "local":
            driver = build_local_driver()
        else:
            assert capabilities is not None
            driver = build_browserstack_driver(capabilities)

        articles = scrape_opinion_articles(driver)

        # Translate headers
        for a in articles:
            a.title_en = translate_title_to_english(a.title_es)

        # Print outputs (as required)
        print_articles_spanish(articles)
        print_translations(articles)

        repeated = find_repeated_words_over_two([a.title_en or "" for a in articles])
        print("\n====================")
        print("REPEATED WORDS (> 2 times) ACROSS TRANSLATED HEADERS")
        print("====================\n")
        if not repeated:
            print("[No words repeated more than twice]")
        else:
            for w, c in repeated:
                print(f"{w}: {c}")

        return articles

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def get_5_browserstack_capabilities() -> List[Dict]:
    """
    5 parallel threads: mix of desktop + mobile.
    Uses W3C style 'bstack:options' as per BrowserStack docs. :contentReference[oaicite:2]{index=2}
    """
    common_bstack_options = {
        "projectName": "ElPais Opinion Scraper",
        "buildName": f"bstack-build-{int(time.time())}",
        "seleniumVersion": "4.21.0",
        "sessionName": "ElPais Opinion - Selenium Assignment",
    }

    return [
        # 1) Windows + Chrome
        {
            "browserName": "Chrome",
            "browserVersion": "latest",
            "bstack:options": {
                **common_bstack_options,
                "os": "Windows",
                "osVersion": "11",
            },
        },
        # 2) Windows + Firefox
        {
            "browserName": "Firefox",
            "browserVersion": "latest",
            "bstack:options": {
                **common_bstack_options,
                "os": "Windows",
                "osVersion": "11",
            },
        },
        # 3) macOS + Safari
        {
            "browserName": "Safari",
            "browserVersion": "latest",
            "bstack:options": {
                **common_bstack_options,
                "os": "OS X",
                "osVersion": "Ventura",
            },
        },
        # 4) Android + Chrome (real device)
        {
            "bstack:options": {
                **common_bstack_options,
                "deviceName": "Samsung Galaxy S23",
                "osVersion": "13.0",
                "realMobile": "true",
            },
            "browserName": "Chrome",
        },
        # 5) iPhone + Safari (real device)
        {
            "bstack:options": {
                **common_bstack_options,
                "deviceName": "iPhone 14",
                "osVersion": "16",
                "realMobile": "true",
            },
            "browserName": "Safari",
        },
    ]


def run_browserstack_parallel(parallel: int = 5) -> None:
    caps_list = get_5_browserstack_capabilities()

    # Keep to exactly 5 as asked
    caps_list = caps_list[:5]
    parallel = min(parallel, len(caps_list))

    print(f"\nRunning on BrowserStack with {parallel} parallel threads...\n")

    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = []
        for i, caps in enumerate(caps_list, start=1):
            caps_copy = dict(caps)
            # Make session names distinct
            bstack_opts = caps_copy.get("bstack:options", {})
            bstack_opts["sessionName"] = f"ElPais Opinion Thread #{i}"
            caps_copy["bstack:options"] = bstack_opts

            futures.append(executor.submit(run_once, "browserstack", caps_copy))

        for f in as_completed(futures):
            try:
                _ = f.result()
            except Exception as e:
                print(f"[Thread failed] {e}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BrowserStack Selenium Assignment: El País Opinion Scraper")
    parser.add_argument("--mode", choices=["local", "browserstack"], required=True, help="Run mode")
    parser.add_argument("--parallel", type=int, default=5, help="Parallel threads for BrowserStack mode")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    safe_mkdir(OUTPUT_DIR)

    args = parse_args()

    if args.mode == "local":
        run_once("local")
    else:
        run_browserstack_parallel(parallel=args.parallel)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)
    except (WebDriverException, TimeoutException) as e:
        print(f"\nSelenium error: {e}")
        sys.exit(2)
    except requests.RequestException as e:
        print(f"\nNetwork/API error: {e}")
        sys.exit(3)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(4)
