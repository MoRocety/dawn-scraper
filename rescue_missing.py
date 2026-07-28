#!/usr/bin/env python3
"""
Rescue missing articles — one script, handles everything.
  - Cloudscraper with find_all('p') → text articles
  - Playwright with anti-detection → JS-rendered pages (cloudscraper cookies shared)
  - Falls back to metadata if no body exists

Output: cache/missing_rescued.json
PDF:    newspapers_fresh/Dawn_Leftovers.pdf
"""

import json, os, time
from cloudscraper import create_scraper
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from fpdf import FPDF

OUTPUT = "cache/missing_rescued.json"
OUTPUT_DIR = "newspapers_fresh"

# ── URLs by expected strategy ──
LIVE_BLOGS = [
    "https://www.dawn.com/news/1909001/pakistan-india-escalation",
    "https://www.dawn.com/news/1909173/pm-shehbaz-addresses-nation-amid-pak-india-escalation",
    "https://www.dawn.com/news/1910350/dg-ispr-addresses-the-nation-after-ceasefire-between-pakistan-and-india",
]

WEB_ONLY_STUBS = [
    "https://www.dawn.com/news/1929284/investing-in-criminal-justice-system-is-investment-in-sustainable-development-and-peace",
    "https://www.dawn.com/news/1978574/asian-development-bank-issues-100m-green-bond",
    "https://www.dawn.com/news/1984175/6-held-in-karachi-as-nccia-busts-call-centre-targeting-foreigners",
]

METADATA_ONLY = [
    "https://www.dawn.com/news/2006960/ghana-world-cup-2026-analysis-semenyo-kudus-amp-inaki-williams-lead-black-stars-dawn-news-english",
    "https://www.dawn.com/news/2006952/canada-world-cup-2026-preview-can-jesse-marsch-lead-canada-to-the-knockouts-dawn-news-english",
    "https://www.dawn.com/news/2006956/belgium-world-cup-preview-de-bruyne-doku-and-the-next-generation-dawn-news-english",
    "https://www.dawn.com/news/2006962/arsenal-lose-ucl-final-to-psg-nba-finals-set-as-spurs-face-knicks-nfl-blockbuster-trades",
    "https://www.dawn.com/news/2006955/world-cup-2026-preview-belgium-egypt-amp-uruguay-dark-horses-and-group-stage-predictions",
    "https://www.dawn.com/news/2009173/knicks-win-nba-finals-jalen-brunson-drops-45-as-new-york-ends-53-year-drought-dawn-news-english",
    "https://www.dawn.com/news/2011881/world-cup-2026-review-ronaldo-masterclass-brazil-dominant-amp-england-stumble-dawn-news-english",
    "https://www.dawn.com/news/2011879/fifa-world-cup-2026-review-contenders-or-pretenders-argentina-france-england-amp-brazil-analyzed",
    "https://www.dawn.com/news/2014165/2026-fifa-world-cup-quarterfinals-set-argentina-miracle-england-survive-ronaldo-out-messi-shines",
    "https://www.dawn.com/news/2016479/spain-v-argentina-world-cup-final-set-england-collapse-messi-through-world-cup-semi-final-review",
    "https://www.dawn.com/news/1973893/chart",
]


def fetch_cloudscraper(url, timeout=15):
    scraper = create_scraper(browser={'custom': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    for attempt in range(5):
        try:
            resp = scraper.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 403, 502, 503, 504):
                time.sleep(min(15, 0.5 * (2 ** attempt)))
        except Exception:
            time.sleep(min(15, 0.5 * (2 ** attempt)))
    return None


def extract_body(soup):
    body_div = soup.select_one(".story__content")
    if not body_div:
        return "", "no-story__content"
    paragraphs = []
    for p in body_div.find_all("p"):
        t = p.get_text(strip=True)
        if t and len(t) > 20:
            paragraphs.append(t)
    return "\n\n".join(paragraphs), "story__content/p"


def extract_meta(soup, url):
    title_el = soup.find("meta", property="og:title")
    title = title_el["content"].strip() if title_el and title_el.get("content") else ""
    time_el = soup.find("meta", property="article:published_time")
    pub_date = time_el["content"][:10] if time_el and time_el.get("content") else ""
    author_links = soup.select(".story__byline__link")
    authors = [a.get_text(strip=True) for a in author_links]
    desc_el = soup.find("meta", property="og:description")
    description = desc_el["content"].strip() if desc_el and desc_el.get("content") else ""
    return {"title": title, "authors": authors, "date": pub_date, "description": description, "url": url}


def scrape_with_playwright(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        page = context.new_page()
        page.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined});')
        try:
            page.goto(url, wait_until="load", timeout=60000)
            page.wait_for_selector(".story__content", state="attached", timeout=10000)
            page.wait_for_timeout(8000)
        except Exception:
            pass
        html = page.content()
        browser.close()
    soup = BeautifulSoup(html, "html.parser")
    body, strategy = extract_body(soup)
    meta = extract_meta(soup, url)
    meta["body"] = body
    meta["strategy"] = f"playwright/{strategy}" if body else "playwright/empty"
    return meta


def scrape_with_cloudscraper(url):
    resp = fetch_cloudscraper(url)
    if not resp:
        return {"url": url, "body": "", "strategy": "fetch-failed", "title": "", "authors": [], "date": "", "description": ""}
    soup = BeautifulSoup(resp.text, "html.parser")
    body, strategy = extract_body(soup)
    meta = extract_meta(soup, url)
    meta["body"] = body
    meta["strategy"] = f"cloudscraper/{strategy}" if body else "cloudscraper/empty"
    return meta


def _clean(text):
    """Replace unicode chars unsupported by Helvetica with ASCII equivalents."""
    result = []
    for ch in text:
        try:
            ch.encode("latin-1")
            result.append(ch)
        except UnicodeEncodeError:
            result.append("?")
    return "".join(result)


def generate_leftover_pdf(rescued):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)

    # Title page
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 16, "DAWN - Leftover Articles", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, "Rescued articles that the main scraper couldn't capture", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(8)

    # TOC
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Contents", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    articles_with_body = [(url, a) for url, a in rescued.items() if a.get("body")]
    articles_without_body = [(url, a) for url, a in rescued.items() if not a.get("body")]

    if articles_with_body:
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, "Articles with text body:", new_x="LMARGIN", new_y="NEXT")
        for i, (url, a) in enumerate(articles_with_body, 1):
            title = _clean(a.get("title", "Untitled")[:100])
            pdf.cell(0, 5, f"{i}. {title}", new_x="LMARGIN", new_y="NEXT")

    if articles_without_body:
        pdf.ln(3)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 5, "Metadata only (video/empty pages):", new_x="LMARGIN", new_y="NEXT")
        for i, (url, a) in enumerate(articles_without_body, 1):
            title = _clean(a.get("title", "Untitled")[:100])
            pdf.cell(0, 5, f"{i}. {title}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_text_color(0, 0, 0)

    # Articles with body
    for url, a in articles_with_body:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 8, _clean(a.get("title", "Untitled")), align="L")
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        meta_line = f"Date: {a.get('date', 'N/A')}"
        if a.get("authors"):
            meta_line += f"  |  By: {', '.join(a['authors'])}"
        pdf.cell(0, 5, _clean(meta_line)[:150], new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        pdf.set_font("Helvetica", "", 10)
        for para in a.get("body", "").split("\n\n"):
            para = _clean(para.strip())
            if para:
                pdf.multi_cell(0, 5.5, para, align="J")
                pdf.ln(3)

    # Metadata-only articles (video/empty)
    if articles_without_body:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "Metadata-Only Articles", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, "These pages have no text body - videos, charts, or stub articles.", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        for url, a in articles_without_body:
            pdf.set_font("Helvetica", "B", 10)
            pdf.multi_cell(0, 6, _clean(a.get("title", "Untitled")))
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(130, 130, 130)
            pdf.cell(0, 4, f"Date: {a.get('date', 'N/A')}  |  URL: {url[-60:]}", new_x="LMARGIN", new_y="NEXT")
            desc = a.get("description", "")
            if desc:
                pdf.set_text_color(60, 60, 60)
                pdf.multi_cell(0, 4, _clean(desc))
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

    path = os.path.join(OUTPUT_DIR, "Dawn_Leftovers.pdf")
    pdf.output(path)
    print(f"PDF saved: {path}")
    return path


def main():
    print("Rescuing missing articles...\n")

    rescued = {}
    ok_count = 0

    # ── Live blogs: Playwright (JS renders iframes/video embeds) ──
    print("── Live blogs (Playwright with anti-detection) ──")
    for url in LIVE_BLOGS:
        print(f"  [{url[-50:]}]", end=" ", flush=True)
        article = scrape_with_playwright(url)
        if article["body"]:
            print(f"OK ({len(article['body'])} chars)")
            ok_count += 1
        else:
            print("EMPTY (video/stub)")
        rescued[url] = article

    # ── Web-only stubs: Playwright ──
    print("\n── Web-only stubs (Playwright) ──")
    for url in WEB_ONLY_STUBS:
        print(f"  [{url[-55:]}]", end=" ", flush=True)
        article = scrape_with_playwright(url)
        if article["body"]:
            print(f"OK ({len(article['body'])} chars)")
            ok_count += 1
        else:
            print("EMPTY (stub)")
        rescued[url] = article

    # ── Videos/Chart: cloudscraper metadata ──
    print("\n── Videos / Chart (cloudscraper, metadata only) ──")
    for url in METADATA_ONLY:
        print(f"  [{url[-55:]}]", end=" ", flush=True)
        article = scrape_with_cloudscraper(url)
        if article["body"]:
            print(f"OK ({len(article['body'])} chars)")
            ok_count += 1
        else:
            print(f"metadata (desc={len(article.get('description',''))} chars)")
        rescued[url] = article

    # ── Save ──
    os.makedirs("cache", exist_ok=True)
    json.dump(rescued, open(OUTPUT, "w"), ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"Rescued with body: {ok_count}/{len(rescued)}")
    print(f"Saved: {OUTPUT}")

    # ── Generate PDF ──
    generate_leftover_pdf(rescued)


if __name__ == "__main__":
    main()
