#!/usr/bin/env python3
"""
Dawn Newspaper Scraper — AIMD congestion-controlled, global cache.
The internet runs on TCP — this scraper runs on the same idea.

Usage:
    python3 scrape_dawn.py                                    # Jan 1 2025 → today
    python3 scrape_dawn.py --start 2026-07-27 --end 2026-07-27  # Test day
    python3 scrape_dawn.py --proxy socks5://host:1080          # Via proxy
"""

import os, sys, json, time, random, logging, threading
from datetime import datetime, timedelta, date
from collections import defaultdict, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

from curl_cffi import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

START_DATE = date(2025, 1, 1)
END_DATE   = date(2026, 7, 27)
BASE       = "https://www.dawn.com"
CACHE_DIR  = "cache"
OUTPUT_DIR = "newspapers"

SECTIONS = OrderedDict([
    ("Front Page",                 "newspaper/front-page"),
    ("Back Page",                  "newspaper/back-page"),
    ("National",                   "newspaper/national"),
    ("Business",                   "newspaper/business"),
    ("International",              "newspaper/international"),
    ("Sport",                      "newspaper/sport"),
    ("Editorial",                  "newspaper/editorial"),
    ("Column",                     "newspaper/column"),
    ("Other Voices",               "newspaper/other-voices"),
    ("50 Years Ago",               "newspaper/50-years-ago"),
    ("70 Years Ago",               "newspaper/70-years-ago"),
    ("75 Years Ago",               "newspaper/75-years-ago"),
    ("Letters",                    "newspaper/letters"),
    ("Books & Authors",            "newspaper/books-authors"),
    ("Business & Finance",         "newspaper/business-finance"),
    ("Young World",                "newspaper/young-world"),
    ("Sunday Magazine",            "newspaper/sunday-magazine"),
    ("Eos",                        "newspaper/eos"),
    ("Icon",                       "newspaper/icon"),
    ("Karachi",                    "newspaper/karachi"),
    ("Lahore",                     "newspaper/lahore"),
    ("Islamabad",                  "newspaper/islamabad"),
    ("Peshawar",                   "newspaper/peshawar"),
    ("Supplements: National Days", "sp-supplements/national-days"),
    ("Supplements: Lifestyle",     "sp-supplements/lifestyle"),
    ("Supplements: Education",     "sp-supplements/education"),
    ("Supplements: Agriculture",   "sp-supplements/agriculture"),
    ("Supplements: Yearender",     "sp-supplements/yearender"),
    ("Latest News",                "latest-news"),
])

IMPERSONATIONS = ["chrome120", "chrome110", "edge99", "safari15"]

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s  %(levelname)s  %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ══════════════════════════════════════════════════════════════════════════
#  Steady-pace Scraper — short backoff, aggressive retry. No learning.
# ══════════════════════════════════════════════════════════════════════════

class DawnScraper:
    def __init__(self, proxy=None, suffix="", max_per_day=0):
        self.proxy = proxy
        self.max_per_day = max_per_day
        self._lock = threading.Lock()

        sfx = f"_{suffix}" if suffix else ""
        self.cache_file = os.path.join(CACHE_DIR, f"articles{sfx}.json")
        self.sections_file = os.path.join(CACHE_DIR, f"sections{sfx}.json")
        self.failed_file = os.path.join(CACHE_DIR, f"failed{sfx}.json")

        os.makedirs(CACHE_DIR, exist_ok=True)
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        self.articles = self._load(self.cache_file)
        self.sections = self._load(self.sections_file)
        self.failed = self._load(self.failed_file)

    def _load(self, path):
        return json.load(open(path)) if os.path.exists(path) else {}

    def _save(self, path, data):
        tmp = path + ".tmp"
        json.dump(data, open(tmp, "w"), ensure_ascii=False)
        os.replace(tmp, path)

    def _save_articles(self):
        self._save(self.cache_file, self.articles)

    def _save_sections(self):
        self._save(self.sections_file, self.sections)

    def _save_failed(self):
        self._save(self.failed_file, self.failed)

    # ── network ──────────────────────────────────────────────────────

    def _fetch(self, url, timeout=15):
        """Exponential backoff on 429/403 — fast initial retry, longer waits if persistent."""
        for attempt in range(20):
            impersonate = IMPERSONATIONS[attempt % len(IMPERSONATIONS)]
            try:
                resp = requests.get(url, timeout=timeout,
                                    impersonate=impersonate, proxy=self.proxy)

                if resp.status_code == 200:
                    return resp

                if resp.status_code in (429, 403, 502, 503, 504):
                    wait = min(30, 0.5 * (2 ** attempt) + random.uniform(0, 0.5))
                    logger.debug("Retry %d/%d %s — sleep %.1fs",
                                 attempt + 1, 20, resp.status_code, wait)
                    time.sleep(wait)
                    continue

                return None  # 404, 410, etc.

            except Exception:
                wait = min(30, 0.5 * (2 ** attempt))
                time.sleep(wait)
                continue

        return None

    # ── URL collection ───────────────────────────────────────────────

    def _extract_article_urls(self, soup):
        urls = set()
        for link in soup.select("article.story h2 a[href]"):
            href = link["href"]
            if "/news/" in href:
                urls.add(urljoin(BASE, href))
        return urls

    def collect_urls(self, start_date, end_date):
        dates = []
        current = start_date
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=1)

        url_tasks = []
        for d in dates:
            ds = d.strftime("%Y-%m-%d")
            for label, path in SECTIONS.items():
                url_tasks.append((f"{BASE}/{path}/{ds}", ds, label))

        logger.info(f"Collecting {len(SECTIONS)} sections × {len(dates)} days = {len(url_tasks)} pages")

        collected = defaultdict(lambda: defaultdict(set))

        def _fetch_one(args):
            url, ds, label = args
            resp = self._fetch(url)
            if not resp:
                return ds, label, set()
            soup = BeautifulSoup(resp.text, "lxml")
            return ds, label, self._extract_article_urls(soup)

        with ThreadPoolExecutor(max_workers=1) as ex:
            futures = {ex.submit(_fetch_one, t): t for t in url_tasks}
            for f in tqdm(as_completed(futures), total=len(futures), desc="Collecting URLs"):
                try:
                    ds, label, urls = f.result()
                    if urls:
                        collected[ds][label].update(urls)
                except Exception:
                    pass

        return collected

    # ── article scraping ─────────────────────────────────────────────

    def scrape_article(self, url):
        if url in self.articles and "body" in self.articles[url]:
            return self.articles[url]

        resp = self._fetch(url)
        if not resp:
            self._track_failure(url)
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        title_el = soup.find("meta", property="og:title")
        title = title_el["content"].strip() if title_el and title_el.get("content") else ""

        author_links = soup.select(".story__byline__link")
        authors = [a.get_text(strip=True) for a in author_links]

        time_el = soup.find("meta", property="article:published_time")
        pub_date = time_el["content"][:10] if time_el and time_el.get("content") else ""

        body_div = soup.select_one(".story__content")
        paragraphs = []
        if body_div:
            for p in body_div.find_all("p", recursive=False):
                t = p.get_text(strip=True)
                if t and len(t) > 20:
                    paragraphs.append(t)

        article = {
            "title": title,
            "authors": authors,
            "date": pub_date,
            "body": "\n\n".join(paragraphs),
            "url": url,
        }

        with self._lock:
            self.articles[url] = article
            self.failed.pop(url, None)

        self._save_articles()  # save after every article — crash-proof
        return article

    def _track_failure(self, url):
        self.failed[url] = {
            "attempts": self.failed.get(url, {}).get("attempts", 0) + 1,
            "last_try": datetime.now().isoformat(),
        }
        self._save_failed()


# ══════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    p = argparse.ArgumentParser(description="Dawn Scraper")
    p.add_argument("--start", default=str(START_DATE))
    p.add_argument("--end", default=str(END_DATE))
    p.add_argument("--proxy", default=None,
                   help="Proxy URL (e.g. socks5://host:1080)")
    p.add_argument("--max-per-day", type=int, default=0,
                   help="Cap articles scraped per day (0 = unlimited, for testing)")
    p.add_argument("--suffix", default="",
                   help="Suffix for cache filenames (for parallel runs)")
    args = p.parse_args()

    scraper = DawnScraper(proxy=args.proxy, suffix=args.suffix,
                          max_per_day=args.max_per_day)

    if args.retry_failed:
        failed_urls = list(scraper.failed.keys())
        logger.info(f"Retrying {len(failed_urls)} failed URLs…")
        for url in tqdm(failed_urls, desc="Retrying failed"):
            scraper.scrape_article(url)
        remaining = sum(1 for u in failed_urls if u in scraper.failed)
        logger.info(f"{len(failed_urls) - remaining} recovered, {remaining} still failed")
        return

    start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_d   = datetime.strptime(args.end, "%Y-%m-%d").date()

    dates = []
    current = start_d
    while current <= end_d:
        dates.append(current)
        current += timedelta(days=1)

    proxy_info = f"proxy {args.proxy}" if args.proxy else "no proxy"
    logger.info(f"Dawn Scraper: {start_d} → {end_d} ({len(dates)} days, {proxy_info})")

    for d in (pbar := tqdm(dates, desc="Processing days")):
        ds = d.strftime("%Y-%m-%d")

        # ── Collection (skip if cached) ──
        if ds in scraper.sections:
            pbar.set_postfix_str(f"cached {ds}")
            day_urls = set()
            for urls in scraper.sections[ds].values():
                day_urls.update(urls)
        else:
            pbar.set_postfix_str(f"collecting {ds}")
            collected = scraper.collect_urls(d, d)
            if collected and ds in collected:
                scraper.sections[ds] = {
                    label: list(urls) for label, urls in collected[ds].items()
                }
                scraper._save_sections()
            day_urls = set()
            for urls in scraper.sections.get(ds, {}).values():
                day_urls.update(urls)

        # ── Scrape ──
        urls_to_scrape = [u for u in day_urls
                          if u not in scraper.articles or "body" not in scraper.articles[u]]

        if scraper.max_per_day and len(urls_to_scrape) > scraper.max_per_day:
            urls_to_scrape = urls_to_scrape[:scraper.max_per_day]

        if urls_to_scrape:
            pbar.set_postfix_str(f"{len(urls_to_scrape)}/{len(day_urls)} for {ds}")
            for url in urls_to_scrape:
                scraper.scrape_article(url)
            # Progress per day is visible through the tqdm postfix

        # Show AIMD state in progress bar
        ok = sum(1 for u in day_urls if scraper.articles.get(u, {}).get("body"))
        total = len(day_urls) if day_urls else 1
        pbar.set_postfix_str(f"{ok}/{total} {ds}")

    # ── Summary ──
    total_ok = sum(1 for v in scraper.articles.values() if v.get("body"))
    total_failed = len(scraper.failed)
    logger.info("─" * 60)
    logger.info(f"Scraped: {total_ok} articles")
    if total_failed:
        logger.warning(f"{total_failed} failed — run: python3 scrape_dawn.py --retry-failed")
    else:
        logger.info("ALL articles scraped — zero failures!")
    logger.info(f"Cache: {os.path.abspath(CACHE_DIR)}/")
    logger.info(f"Generate PDFs: python3 generate_pdfs.py")


if __name__ == "__main__":
    main()
