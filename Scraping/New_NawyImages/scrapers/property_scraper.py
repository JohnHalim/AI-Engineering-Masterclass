import asyncio
import logging

from config import BASE_URL, POLITENESS_DELAY_S, UNITS_PAGE_SIZE
from services.json_client import JsonClient
from utils.url_utils import compound_json_url

log = logging.getLogger("nawy.property_scraper")


class PropertyScraper:
    """
    Discovers unit slugs for a compound, and (later) fetches
    images/floor plans for individual units.
    """

    def __init__(self, json_client: JsonClient, build_id: str):
        self._client   = json_client
        self._build_id = build_id

    async def get_unit_slugs(self, compound_slug: str) -> list[str]:
        """
        Return all unit slugs for a compound/phase.
        Tries strategies in order, returns on first non-empty result.
        """
        # Strategy 1: availablePropertyTypes inside compound JSON (confirmed working)
        slugs = await self._strategy_available_property_types(compound_slug)
        if slugs:
            log.info(f"  [{compound_slug}] units via availablePropertyTypes: {len(slugs)}")
            return slugs

        # Strategy 2: properties/units embedded directly at top level of compound JSON
        slugs = await self._strategy_compound_embed(compound_slug)
        if slugs:
            log.info(f"  [{compound_slug}] units via compound-embed: {len(slugs)}")
            return slugs

        # Strategy 3: listing-api.nawy.com paginated search
        slugs = await self._strategy_listing_api(compound_slug)
        if slugs:
            log.info(f"  [{compound_slug}] units via listing-api: {len(slugs)}")
            return slugs

        # Strategy 4: _next/data with ?page= query param
        slugs = await self._strategy_next_pagination(compound_slug)
        log.info(f"  [{compound_slug}] units via next-pagination: {len(slugs)}")
        return slugs
    
    
    async def scrape(self, compound_slug: str, unit_slug: str) -> "Property":
        """
        Fetch images and floor plans for one unit.
        Returns a Property with empty lists if the page cannot be fetched.
        """
        from models import Property
        from utils.url_utils import property_json_url, extract_image_url

        url  = property_json_url(BASE_URL, self._build_id, compound_slug, unit_slug)
        data = await self._client.get(url)

        if not data:
            return Property(slug=unit_slug)

        # unit data sits under pageProps.property or pageProps.unit
        page_props = data.get("pageProps", {})
        raw = (
            page_props.get("property")
            or page_props.get("unit")
            or {}
        )

        images      = self._extract_urls(raw.get("images")     or [])
        floor_plans = self._extract_urls(raw.get("floorPlans") or raw.get("floor_plans") or [])

        return Property(slug=unit_slug, images=images, floor_plans=floor_plans)

    @staticmethod
    def _extract_urls(items: list) -> list[str]:
        """Normalise image items — either plain strings or dicts with a url key."""
        from utils.url_utils import extract_image_url
        urls: list[str] = []
        seen: set[str]  = set()
        for item in items:
            url = extract_image_url(item)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls
        
    

    # ── Strategy 1: availablePropertyTypes (confirmed by DevTools) ──

    async def _strategy_available_property_types(self, compound_slug: str) -> list[str]:
        url  = compound_json_url(BASE_URL, self._build_id, compound_slug)
        data = await self._client.get(url)
        if not data:
            return []

        # availablePropertyTypes lives under pageProps directly, NOT under compound
        page_props = data.get("pageProps", {})
        apt        = page_props.get("availablePropertyTypes") or []

        slugs: list[str] = []
        seen:  set[str]  = set()

        for ptype in apt:
            for prop in (ptype.get("properties") or []):
                slug = prop.get("slug") or prop.get("slugEn")
                if slug and slug not in seen:
                    seen.add(slug)
                    slugs.append(slug)

        return slugs

    # ── Strategy 2: top-level properties/units embed ─────────────

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

    # ── Strategy 3: listing-api.nawy.com ─────────────────────────

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

    # ── Strategy 4: _next/data with ?page= param ─────────────────

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

            compound   = (
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

    # ── Shared helper ─────────────────────────────────────────────

    @staticmethod
    def _slugs_from_list(items: list) -> list[str]:
        seen:  set[str]  = set()
        slugs: list[str] = []
        for item in items:
            slug = item.get("slug") or item.get("slugEn")
            if slug and slug not in seen:
                seen.add(slug)
                slugs.append(slug)
        return slugs