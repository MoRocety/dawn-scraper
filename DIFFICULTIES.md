# Dawn Newspaper Scraping — Difficulties Summary

## Goal
Scrape all Dawn.com newspaper articles from Jan 1, 2025 to today (~573 days, ~400 articles/day) into per-day PDFs organized by section.

## What Works
- Article pages scrape cleanly — `.story__content` for body, meta tags for title/date/author
- 29 newspaper sections identified with date-filterable URL pattern: `/newspaper/{section}/{YYYY-MM-DD}`
- `curl_cffi` with Chrome impersonation bypasses Cloudflare (bare `requests` gets 403)
- Incremental cache saving every article — crash-proof
- PDF generation works via `fpdf2` (weasyprint fails on macOS due to system library naming)

## Core Problem: Dawn's Aggressive Rate Limiting
- **Even at 1 request every 1.5 seconds**, 45% get HTTP 429 (too many requests)
- **1 worker, no concurrency** still gets ~45% 429 rate — it's a volume-over-time limit, not concurrency
- **More workers = more 429s**: 2 workers drops throughput, 3-4 workers makes it worse
- **AIMD (TCP congestion control) fails**: Dawn 429s at ANY speed, so the algorithm just ratchets delay up to infinity
- **Best throughput**: 1 worker, 0 delay, short retry backoff (~0.9 articles/sec effective)
- At 0.9/sec, ~400 articles/day = 7.5 min/day, 573 days = ~72 hours single machine

## Failed Approaches
1. **Multi-process on same machine**: Same IP = same rate limit. 2 processes just split the same budget, net gain ~14%
2. **Free HTTP proxies**: All dead/slow. Tested proxyscrape API, 3 manual proxies — all timeout or 403
3. **Tor**: Free but extremely slow (~150ms latency minimum), dawn.com blocks most Tor exit nodes
4. **`max_attempts=1` with retry-later**: 55% success first pass, 45% deferred to `--retry-failed`. Bottom-line throughput doesn't improve vs just retrying inline
5. **AIMD congestion control**: Doubles delay on each 429, never recovers because Dawn 429s at any speed

## What Would Help (But Not Free)
1. **Residential proxy service** ($5-10/month): Each proxy IP gets its own rate-limit budget. Rotate 5-10 IPs = 5-10x throughput
2. **Multiple physical machines with different IPs**: Each machine = independent rate limit. 5 machines = 5x throughput
3. **GitHub Actions**: Free tier gives 20 parallel runners, each with a fresh IP. Could split date range across 20 jobs for ~6 hour total wall clock

## Current State
Running single-machine with `caffeinate -s` (lid-close safe). 120-day test batch (Jan-Apr 2025) will take ~18 hours at current rate.

## Question for Claude
Is there a way to get rotating/multiple IPs for free that actually works? Or should we just accept the slow pace and let GitHub Actions handle the parallelism?
