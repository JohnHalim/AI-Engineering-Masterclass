"""
scrapers/property_scraper.py
─────────────────────────────
PropertyScraper — responsible for two things:

  1. get_unit_slugs()  — discover all unit slugs for a given compound slug
                         (tries three API strategies in order)

  2. scrape()          — fetch images + floor plans for a single unit slug
"""

import asyncio
import logging
from typing import Optional

from config import BASE_URL, POLITENESS_DELAY_S, UNITS_PAGE_SIZE
from models import Property
from services.json_client import JsonClient
from utils.url_utils import compound_json_url, property_json_url, extract_image_url

log = logging.getLogger("nawy.property_scraper")


class PropertyScraper:
    """
    Fetches property/unit data from Nawy's APIs.

    Unit discovery uses three fallback strategies because Nawy
    serves unit lists from different endpoints depending on the
    compound type and deployment version.
    """

    def __init__(self, json_client: JsonClient, build_id: str):
        self._client   = json_client
        self._build_id = build_id

    # ── Unit slug discovery ────────────────────────────────────────

    async def get_unit_slugs(self, compound_slug: str) -> list[str]:
        """
        Return all unit slugs for a compound.
        Tries three strategies in order, returns on first success.
        """
        slugs = await self._strategy_compound_embed(compound_slug)
        if slugs:
            log.debug(f"    [{compound_slug}] unit slugs via compound embed: {len(slugs)}")
            return slugs

        slugs = await self._strategy_listing_api(compound_slug)
        if slugs:
            log.debug(f"    [{compound_slug}] unit slugs via listing API: {len(slugs)}")
            return slugs

        slugs = await self._strategy_next_pagination(compound_slug)
        log.debug(f"    [{compound_slug}] unit slugs after all strategies: {len(slugs)}")
        return slugs

    # ── Single unit fetch ──────────────────────────────────────────

    async def scrape(self, compound_slug: str, unit_slug: str) -> Property:
        """
        Fetch images and floor plans for one unit.
        Returns a Property with empty lists if the page cannot be fetched.
        """
        url  = property_json_url(BASE_URL, self._build_id, compound_slug, unit_slug)
        data = await self._client.get(url)

        if not data:
            return Property(slug=unit_slug)

        raw = self._unwrap_property(data)

        images      = self._extract_urls(raw.get("images")     or [])
        floor_plans = self._extract_urls(raw.get("floorPlans") or raw.get("floor_plans") or [])

        return Property(slug=unit_slug, images=images, floor_plans=floor_plans)

    # ── Strategy 1: properties embedded in compound JSON ──────────

    async def _strategy_compound_embed(self, compound_slug: str) -> list[str]:
        url  = compound_json_url(BASE_URL, self._build_id, compound_slug)
        data = await self._client.get(url)
        if not data:
            return []

        compound = (
            data.get("pageProps", {}).get("compound")
            or data.get("compound")
            or {}
        )
        raw_list = compound.get("properties") or compound.get("units") or []
        return self._slugs_from_list(raw_list)

    # ── Strategy 2: listing-api.nawy.com paginated endpoint ───────

    async def _strategy_listing_api(self, compound_slug: str) -> list[str]:
        slugs:    list[str] = []
        page_num: int       = 1

        while True:
            url = (
                f"https://listing-api.nawy.com/v1/search"
                f"?compoundSlug={compound_slug}"
                f"&pageSize={UNITS_PAGE_SIZE}"
                f"&pageNumber={page_num}"
            )
            data = await self._client.get(url)
            if not data:
                break

            properties = (
                data.get("properties")
                or data.get("data", {}).get("properties")
                or data.get("results")
                or data.get("items")
                or []
            )
            if not properties:
                break

            slugs.extend(self._slugs_from_list(properties))

            total     = int(data.get("total") or data.get("data", {}).get("total") or 0)
            retrieved = page_num * UNITS_PAGE_SIZE
            if retrieved >= total or len(properties) < UNITS_PAGE_SIZE:
                break

            page_num += 1
            await asyncio.sleep(POLITENESS_DELAY_S)

        return slugs

    # ── Strategy 3: _next/data with ?page= query param ────────────

    async def _strategy_next_pagination(self, compound_slug: str) -> list[str]:
        slugs:    list[str] = []
        page_num: int       = 1

        while True:
            url = (
                f"{BASE_URL}/_next/data/{self._build_id}/en/compound/{compound_slug}.json"
                f"?page={page_num}"
            )
            data = await self._client.get(url)
            if not data:
                break

            compound = (
                data.get("pageProps", {}).get("compound")
                or data.get("compound")
                or {}
            )
            properties = compound.get("properties") or compound.get("units") or []
            if not properties:
                break

            slugs.extend(self._slugs_from_list(properties))

            total = int(compound.get("propertiesCount") or compound.get("unitsCount") or 0)
            if len(slugs) >= total or len(properties) < UNITS_PAGE_SIZE:
                break

            page_num += 1
            await asyncio.sleep(POLITENESS_DELAY_S)

        return slugs

    # ── Shared helpers ─────────────────────────────────────────────

    @staticmethod
    def _unwrap_property(data: dict) -> dict:
        """Navigate past Next.js pageProps to reach the property object."""
        return (
            data.get("pageProps", {}).get("property")
            or data.get("pageProps", {}).get("unit")
            or data.get("property")
            or data.get("unit")
            or data
        )

    @staticmethod
    def _slugs_from_list(items: list) -> list[str]:
        """Extract unique slugs from a list of property objects."""
        seen:  set[str]  = set()
        slugs: list[str] = []
        for item in items:
            slug = item.get("slug") or item.get("slugEn")
            if slug and slug not in seen:
                seen.add(slug)
                slugs.append(slug)
        return slugs

    @staticmethod
    def _extract_urls(items: list) -> list[str]:
        """Normalise a list of image items (string or dict) to plain URL strings."""
        urls = []
        seen: set[str] = set()
        for item in items:
            url = extract_image_url(item)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls
