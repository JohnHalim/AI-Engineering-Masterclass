"""
scrapers/compound_scraper.py
─────────────────────────────
CompoundScraper — fetches the Next.js JSON for a compound page
and builds a fully populated Compound dataclass (images + phases).

Note: unit slugs are fetched by PropertyScraper, not here.
"""

import asyncio
import logging
from typing import Optional

from config import BASE_URL, POLITENESS_DELAY_S
from models import Compound, Phase
from services.json_client import JsonClient
from utils.url_utils import compound_json_url, extract_image_url

log = logging.getLogger("nawy.compound_scraper")


class CompoundScraper:
    """
    Fetches and parses compound-level data from the Nawy Next.js API.

    What it returns per compound:
      • compound-level images  (gallery + master plan)
      • list of Phase objects  (slug, name, thumbnail image)
    """

    def __init__(self, json_client: JsonClient, build_id: str):
        self._client   = json_client
        self._build_id = build_id

    async def scrape(self, compound_slug: str) -> Optional[Compound]:
        """
        Fetch and parse a compound.
        Returns a Compound dataclass, or None if the page cannot be fetched.
        """
        url  = compound_json_url(BASE_URL, self._build_id, compound_slug)
        data = await self._client.get(url)

        if not data:
            log.warning(f"No data returned for compound: {compound_slug}")
            return None

        raw = self._unwrap(data)
        if not raw:
            log.warning(f"Unexpected JSON shape for compound: {compound_slug}")
            return None

        name   = raw.get("name") or raw.get("displayName") or compound_slug
        images = self._parse_images(raw)
        phases = self._parse_phases(raw)

        log.info(
            f"  {name}: "
            f"{len(images)} images | "
            f"{len(phases)} phase(s)"
        )

        return Compound(
            slug=compound_slug,
            name=name,
            images=images,
            phases=phases,
        )

    async def scrape_phase(self, phase_meta: Phase) -> Phase:
        """
        Enrich a Phase object with its full image list.
        A phase is itself a compound in Nawy's data model —
        it has its own compound JSON endpoint.
        """
        url  = compound_json_url(BASE_URL, self._build_id, phase_meta.slug)
        data = await self._client.get(url)

        images = list(phase_meta.images)  # start with the thumbnail we already have

        if data:
            raw          = self._unwrap(data) or {}
            phase_images = self._parse_images(raw)
            seen         = set(images)
            for img in phase_images:
                if img not in seen:
                    images.append(img)
                    seen.add(img)

        return Phase(
            slug=phase_meta.slug,
            name=phase_meta.name,
            images=images,
            unit_slugs=phase_meta.unit_slugs,  # filled in by PropertyScraper
        )

    # ── Private helpers ────────────────────────────────────────────

    @staticmethod
    def _unwrap(data: dict) -> Optional[dict]:
        """Navigate past Next.js pageProps wrapper to reach the compound object."""
        return (
            data.get("pageProps", {}).get("compound")
            or data.get("compound")
        )

    @staticmethod
    def _parse_images(raw: dict) -> list[str]:
        """
        Extract all image URLs from a compound JSON object.
        Includes the master plan image when present.
        """
        images: list[str] = []
        seen:   set[str]  = set()

        for item in (raw.get("images") or []):
            url = extract_image_url(item)
            if url and url not in seen:
                seen.add(url)
                images.append(url)

        master = raw.get("masterPlan")
        if master and master not in seen:
            images.append(master)

        return images

    @staticmethod
    def _parse_phases(raw: dict) -> list[Phase]:
        """Extract Phase stubs from the compound JSON (slug, name, thumbnail)."""
        phases: list[Phase] = []

        for ph in (raw.get("phases") or []):
            slug = ph.get("slug") or ph.get("slugEn")
            if not slug:
                continue
            name      = ph.get("name") or slug
            thumbnail = ph.get("imageUrl") or ph.get("image") or ""
            phases.append(Phase(
                slug=slug,
                name=name,
                images=[thumbnail] if thumbnail else [],
            ))

        return phases
