import asyncio
import logging

import httpx

from config import SLUGS_CACHE_FILE, POLITENESS_DELAY_S, HTTP_HEADERS
from utils.file_utils import load_json, save_json

log = logging.getLogger("nawy.search_scraper")

SEARCH_API_URL = "https://listing-api.nawy.com/v1/search/compounds"
PAGE_SIZE      = 50  # max out the page size to reduce number of requests


class SearchScraper:
    """
    Fetches all compound slugs from the Nawy listing API.
    Paginates through all pages until every compound is collected.
    Results cached to SLUGS_CACHE_FILE so re-runs skip this phase.
    No browser needed — pure HTTP.
    """

    def __init__(self, client: httpx.AsyncClient):
        self._client = client
        
    async def get_compound_slugs(self) -> list[str]:
        """Return all compound slugs. Loads from cache if available."""
        cached = load_json(SLUGS_CACHE_FILE)
        if cached:
            log.info(f"Loaded {len(cached)} slugs from cache ({SLUGS_CACHE_FILE})")
            return cached

        slugs = await self._fetch_all_pages()
        save_json(SLUGS_CACHE_FILE, slugs)
        log.info(f"Saved {len(slugs)} slugs to {SLUGS_CACHE_FILE}")
        return slugs
    
    async def _fetch_all_pages(self) -> list[str]:
        slugs:    list[str] = []
        page_num: int       = 1

        # fetch page 1 first to get the total count
        data  = await self._fetch_page(page_num)
        total = data.get("total", 0)
        slugs.extend(self._extract_slugs(data))
        log.info(f"  page {page_num} → {len(slugs)}/{total} compounds")

        # calculate remaining pages
        import math
        total_pages = math.ceil(total / PAGE_SIZE)

        for page_num in range(2, total_pages + 1):
            await asyncio.sleep(POLITENESS_DELAY_S)
            data = await self._fetch_page(page_num)
            new  = self._extract_slugs(data)
            slugs.extend(new)
            log.info(f"  page {page_num}/{total_pages} → {len(slugs)}/{total} compounds")

        return slugs

    async def _fetch_page(self, page: int) -> dict:
        """Fetch one page of compounds from the listing API."""
        params = {"page": page, "pageSize": PAGE_SIZE}
        r = await self._client.get(
            SEARCH_API_URL,
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _extract_slugs(data: dict) -> list[str]:
        """Pull slugs out of a page response."""
        results = data.get("results") or data.get("compounds") or []
        return [
            item["slug"]
            for item in results
            if item.get("slug")
        ]
