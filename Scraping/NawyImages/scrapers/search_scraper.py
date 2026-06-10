"""
scrapers/search_scraper.py
───────────────────────────
SearchScraper — opens nawy.com/search in a headless browser,
scrolls until all compound cards are loaded, and returns every
compound slug found on the page.

Why a headless browser?
  The search page is a React app.  Compounds are rendered by
  JavaScript after the page loads — plain HTTP requests only
  get an empty HTML shell.  Playwright lets the JS run first.
"""

import logging
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PwTimeout

from config import SEARCH_URL, SCROLL_PAUSE_MS, SCROLL_STALE_LIMIT, SLUGS_CACHE_FILE
from utils.file_utils import load_json, save_json

log = logging.getLogger("nawy.search_scraper")


class SearchScraper:
    """
    Collects all compound slugs from nawy.com/search by scrolling
    the page until no new compounds appear.

    Results are cached to SLUGS_CACHE_FILE so subsequent runs skip
    this phase entirely.
    """

    async def get_compound_slugs(self) -> list[str]:
        """
        Return all compound slugs found on /search.
        Loads from cache if available; otherwise launches the browser.
        """
        cached = load_json(SLUGS_CACHE_FILE)
        if cached:
            log.info(f"Loaded {len(cached)} slugs from cache ({SLUGS_CACHE_FILE})")
            return cached

        slugs = await self._scroll_and_collect()
        save_json(SLUGS_CACHE_FILE, slugs)
        log.info(f"Saved {len(slugs)} slugs to {SLUGS_CACHE_FILE}")
        return slugs

    # ── Internal ───────────────────────────────────────────────────

    async def _scroll_and_collect(self) -> list[str]:
        log.info("Launching headless browser → nawy.com/search …")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page    = await browser.new_page()

            await page.goto(SEARCH_URL, wait_until="networkidle", timeout=60_000)

            slugs      = await self._harvest_slugs(page)
            prev_count = len(slugs)
            stale      = 0

            log.info(f"Starting scroll — {prev_count} compounds visible initially")

            while stale < SCROLL_STALE_LIMIT:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(SCROLL_PAUSE_MS)

                slugs      = await self._harvest_slugs(page)
                curr_count = len(slugs)

                log.info(f"  scroll round — {curr_count} compounds found …")

                if curr_count == prev_count:
                    stale += 1
                else:
                    stale      = 0
                    prev_count = curr_count

            await browser.close()

        log.info(f"Scroll complete — {len(slugs)} compound slugs collected")
        return slugs

    @staticmethod
    async def _harvest_slugs(page) -> list[str]:
        """Extract all unique /compound/<slug> hrefs from the current DOM."""
        handles = await page.query_selector_all('a[href*="/compound/"]')
        seen:  set[str]  = set()
        slugs: list[str] = []

        for handle in handles:
            href = await handle.get_attribute("href")
            if not href:
                continue
            slug = href.strip("/").split("/")[-1]
            if slug and slug not in seen:
                seen.add(slug)
                slugs.append(slug)

        return slugs
