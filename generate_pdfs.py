#!/usr/bin/env python3
"""
Dawn PDF Generator — reads scraped cache and generates per-day PDFs.
Works even if scraping was interrupted mid-run.

Usage:
    python3 generate_pdfs.py --pid 12345                    # From one process cache
    python3 generate_pdfs.py --pid 12345 --start 2026-07-27 --end 2026-07-27
    python3 generate_pdfs.py --merge                        # Merge all PID caches, generate all PDFs
"""

import os, sys, json, glob, logging
from datetime import datetime, date, timedelta
from collections import OrderedDict

from tqdm import tqdm
from fpdf import FPDF

CACHE_DIR = "cache"
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

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s  %(levelname)s  %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def load_json(path):
    return json.load(open(path)) if os.path.exists(path) else {}


def _clean(s):
    replacements = {
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "--", "\u00a0": " ",
        "\u2010": "-", "\u2026": "...", "\u00b0": " deg",
        "\u2012": "-", "\u2032": "'", "\u2033": '"',
        "\u00e9": "e", "\u00e1": "a", "\u00ed": "i",
        "\u00f3": "o", "\u00fa": "u", "\u00f1": "n",
        "\u00c9": "E", "\u00c1": "A", "\u00cd": "I",
        "\u00d3": "O", "\u00da": "U", "\u00d1": "N",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    result = []
    for ch in s:
        try:
            ch.encode("latin-1")
            result.append(ch)
        except UnicodeEncodeError:
            result.append("?")
    return "".join(result)


def generate_pdf(date_str, sections_data):
    has_content = any(arts for arts in sections_data.values())
    if not has_content:
        return None

    date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %B %d, %Y")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)

    # Masthead
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 28)
    pdf.cell(0, 16, "DAWN", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, date_fmt, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.line(10, pdf.get_y() + 4, 200, pdf.get_y() + 4)
    pdf.ln(10)

    # TOC
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Contents", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)

    toc_num = 1
    for label, articles in sections_data.items():
        if not articles:
            continue
        for a in sorted(articles, key=lambda x: x.get("title", "")):
            title = _clean(a["title"][:100])
            pdf.cell(0, 5, f"{toc_num}. {title}", new_x="LMARGIN", new_y="NEXT")
            toc_num += 1

    pdf.set_text_color(0, 0, 0)

    # Articles by section
    for label, articles in sections_data.items():
        if not articles:
            continue

        pdf.add_page()
        pdf.set_font("Helvetica", "B", 22)
        pdf.cell(0, 120, "", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 14, label.upper(), new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.line(60, pdf.get_y() + 4, 150, pdf.get_y() + 4)

        for a in sorted(articles, key=lambda x: x.get("title", "")):
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(130, 130, 130)
            pdf.cell(0, 5, label.upper(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

            pdf.set_font("Helvetica", "B", 14)
            pdf.multi_cell(0, 7, _clean(a.get("title", "Untitled")), align="L")

            authors = ", ".join(a.get("authors", []))
            if authors:
                pdf.set_x(10)
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(120, 120, 120)
                pdf.cell(180, 5, _clean(f"By {authors}")[:150],
                         new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            pdf.ln(4)
            pdf.set_font("Helvetica", "", 10)
            body = a.get("body", "")
            for para in body.split("\n\n"):
                para = _clean(para.strip())
                if para:
                    pdf.multi_cell(0, 5.5, para, align="J")
                    pdf.ln(2)

    path = os.path.join(OUTPUT_DIR, f"Dawn_{date_str}.pdf")
    try:
        pdf.output(path)
        return path
    except Exception as e:
        logger.error(f"PDF failed {date_str}: {e}")
        return None


def build_sections_data(ds, articles, sections):
    """Build sections_data from articles cache and section→url mapping."""
    sections_data = OrderedDict()
    section_urls = sections.get(ds, {})

    if section_urls:
        # Full section mapping available
        for label in SECTIONS:
            urls = set(section_urls.get(label, []))
            arts = [articles[u] for u in urls if u in articles and "body" in articles[u]]
            sections_data[label] = arts
    else:
        # No section mapping — group by date only
        all_arts = [a for a in articles.values()
                    if a.get("date") == ds and a.get("body")]
        for label in SECTIONS:
            sections_data[label] = []
        sections_data["Articles"] = all_arts

    return sections_data


def main():
    import argparse
    p = argparse.ArgumentParser(description="Dawn PDF Generator")
    p.add_argument("--pid", type=int, default=None,
                   help="Process ID to read cache from (articles_{pid}.json)")
    p.add_argument("--merge", action="store_true",
                   help="Merge all PID caches and generate PDFs")
    p.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    p.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    args = p.parse_args()

    if args.merge:
        articles = {}
        sections = {}
        for af in sorted(glob.glob(f"{CACHE_DIR}/articles*.json")):
            articles.update(load_json(af))
            # Derive sections filename from articles filename
            sf = af.replace("articles", "sections")
            if os.path.exists(sf):
                for ds, secs in load_json(sf).items():
                    if ds not in sections:
                        sections[ds] = {}
                    for label, urls in secs.items():
                        sections[ds][label] = urls
    elif args.pid:
        articles = load_json(f"{CACHE_DIR}/articles_{args.pid}.json")
        sections = load_json(f"{CACHE_DIR}/sections_{args.pid}.json")
    else:
        # Auto-detect
        files = sorted(glob.glob(f"{CACHE_DIR}/articles*.json"))
        if not files:
            logger.error("No cache files found in %s/", CACHE_DIR)
            sys.exit(1)
        articles_file = files[0]
        sections_file = articles_file.replace("articles", "sections")
        logger.info(f"Using cache: {articles_file}")
        articles = load_json(articles_file)
        sections = load_json(sections_file) if os.path.exists(sections_file) else {}

    # Find date range
    all_dates = set()
    for a in articles.values():
        if a.get("date"):
            all_dates.add(a["date"])
    for ds in sections:
        all_dates.add(ds)

    if not all_dates:
        logger.error("No dates found in cache")
        sys.exit(1)

    if args.start:
        start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
    else:
        start_d = date.fromisoformat(min(all_dates))

    if args.end:
        end_d = datetime.strptime(args.end, "%Y-%m-%d").date()
    else:
        end_d = date.fromisoformat(max(all_dates))

    logger.info(f"Generating PDFs: {start_d} → {end_d}")

    count = 0
    current = start_d
    while current <= end_d:
        ds = current.strftime("%Y-%m-%d")
        sections_data = build_sections_data(ds, articles, sections)
        if generate_pdf(ds, sections_data):
            count += 1
        current += timedelta(days=1)

    logger.info(f"Done — {count} PDFs in '{os.path.abspath(OUTPUT_DIR)}/'")


if __name__ == "__main__":
    main()
