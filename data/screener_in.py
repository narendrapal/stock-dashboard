"""
Screener.in integration
=======================
1. PUBLIC  — Scrape company name, sector, industry from public pages.
             No login needed. Cached 30 days.
2. AUTHENTICATED — Import user watchlists via session login.
             Credentials never stored to disk; passed in at runtime.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.screener.in"
_CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache", "screener_company.json")
_CACHE_DAYS = 30

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(data: dict):
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"screener cache write error: {e}")


def _fresh(entry: dict, days: int = _CACHE_DAYS) -> bool:
    ts = entry.get("cached_at")
    return bool(ts) and datetime.now() - datetime.fromisoformat(ts) < timedelta(days=days)


def _clean(symbol: str) -> str:
    """Strip exchange suffix → screener.in ticker."""
    return symbol.replace(".NS", "").replace(".BO", "").upper()


# ── Public scraping ────────────────────────────────────────────────────────────

def scrape_company(symbol: str) -> dict:
    """
    Fetch name, sector, industry from a public screener.in company page.
    Returns dict with keys: symbol, name, sector, industry, cached_at.
    Result is disk-cached for 30 days.
    """
    cache = _load_cache()
    key = _clean(symbol)

    if key in cache and _fresh(cache[key]):
        return cache[key]

    result = {
        "symbol": symbol,
        "name": key,
        "sector": "",
        "industry": "",
        "cached_at": datetime.now().isoformat(),
    }

    for url in [f"{BASE_URL}/company/{key}/", f"{BASE_URL}/company/{key}/consolidated/"]:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=12, allow_redirects=True)
            if r.status_code != 200 or "company" not in r.url:
                continue

            soup = BeautifulSoup(r.text, "lxml")

            # ── Company name ──
            h1 = soup.find("h1")
            if h1:
                result["name"] = h1.get_text(" ", strip=True)

            # ── Sector & Industry ──
            # screener.in embeds links like /screen/sector/Banks/ and /screen/industry/Banks/
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True)
                if not text:
                    continue
                if "/screen/sector/" in href and not result["sector"]:
                    result["sector"] = text
                if "/screen/industry/" in href and not result["industry"]:
                    result["industry"] = text
                if result["sector"] and result["industry"]:
                    break

            # Fallback: breadcrumb nav
            if not result["sector"]:
                bc = soup.find("ul", class_=re.compile("breadcrumb", re.I))
                if bc:
                    items = [a.get_text(strip=True) for a in bc.find_all("a")]
                    if len(items) >= 2:
                        result["sector"] = items[1]
                    if len(items) >= 3:
                        result["industry"] = items[2]

            if result["sector"] or result["name"] != key:
                break  # got useful data; stop trying URLs

        except Exception as e:
            logger.debug(f"screener.in scrape error for {key}: {e}")

    time.sleep(0.25)   # polite delay between requests
    cache[key] = result
    _save_cache(cache)
    return result


def get_bulk_screener_info(symbols: list, on_progress=None) -> dict:
    """
    Bulk-fetch screener.in info for a list of NSE symbols.
    Uses disk cache — only fetches what is missing / stale.
    on_progress(done: int, total: int) is called after each symbol.
    Returns {symbol: {name, sector, industry, ...}}
    """
    cache = _load_cache()
    results = {}

    for i, sym in enumerate(symbols):
        key = _clean(sym)
        if key in cache and _fresh(cache[key]):
            results[sym] = cache[key]
        else:
            results[sym] = scrape_company(sym)
        if on_progress:
            on_progress(i + 1, len(symbols))

    return results


def get_cache_stats() -> dict:
    """Returns {total_cached, stale_count, cache_file_kb}."""
    cache = _load_cache()
    total = len(cache)
    stale = sum(1 for v in cache.values() if not _fresh(v))
    size_kb = round(os.path.getsize(_CACHE_FILE) / 1024, 1) if os.path.exists(_CACHE_FILE) else 0
    return {"total_cached": total, "stale_count": stale, "size_kb": size_kb}


# ── Authenticated import ───────────────────────────────────────────────────────

def login(username: str, password: str) -> "requests.Session | None":
    """
    Log in to screener.in.
    Returns an authenticated requests.Session or None on failure.
    Credentials are NEVER written to disk.
    """
    session = requests.Session()
    session.headers.update(_HEADERS)
    try:
        r = session.get(f"{BASE_URL}/login/", timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        csrf_tag = soup.find("input", {"name": "csrfmiddlewaretoken"})
        if not csrf_tag:
            logger.error("CSRF token not found on screener.in login page")
            return None

        resp = session.post(
            f"{BASE_URL}/login/",
            data={
                "username": username,
                "password": password,
                "csrfmiddlewaretoken": csrf_tag["value"],
                "next": "/",
            },
            headers={"Referer": f"{BASE_URL}/login/"},
            allow_redirects=True,
            timeout=10,
        )
        if "/login/" in resp.url or "error" in resp.text.lower()[:500]:
            logger.warning("screener.in login failed — wrong credentials?")
            return None
        logger.info("screener.in login successful")
        return session
    except Exception as e:
        logger.error(f"screener.in login error: {e}")
        return None


def fetch_watchlists(session: "requests.Session") -> dict:
    """
    Fetch all user watchlists from screener.in.
    Returns {watchlist_name: [NSE_symbol_with_.NS, ...]}
    """
    watchlists: dict = {}
    try:
        r = session.get(f"{BASE_URL}/watchlist/", timeout=10)
        soup = BeautifulSoup(r.text, "lxml")

        # Watchlist items: /watchlist/{id}/ links
        wl_links = soup.find_all("a", href=re.compile(r"^/watchlist/\d+"))
        seen_urls: set = set()

        for link in wl_links:
            href = link["href"].rstrip("/") + "/"
            if href in seen_urls:
                continue
            seen_urls.add(href)
            wl_name = link.get_text(strip=True)
            if not wl_name:
                continue

            try:
                wr = session.get(BASE_URL + href, timeout=12)
                wsoup = BeautifulSoup(wr.text, "lxml")

                # Company links: /company/SYMBOL/ (all-caps NSE ticker)
                company_links = wsoup.find_all(
                    "a", href=re.compile(r"/company/[A-Z0-9&%.-]+/"))
                symbols = []
                for cl in company_links:
                    m = re.search(r"/company/([A-Z0-9&%.-]+)/", cl["href"])
                    if m:
                        raw_sym = m.group(1)
                        if len(raw_sym) <= 20:   # skip long garbage matches
                            symbols.append(raw_sym + ".NS")

                symbols = list(dict.fromkeys(symbols))  # dedup, preserve order
                if symbols:
                    watchlists[wl_name] = symbols
                    logger.info(f"Screener watchlist '{wl_name}': {len(symbols)} stocks")
                time.sleep(0.3)
            except Exception as e:
                logger.debug(f"Error fetching watchlist '{wl_name}': {e}")

    except Exception as e:
        logger.error(f"Error fetching screener.in watchlists: {e}")

    return watchlists
