import logging
from typing import Optional

from config import BASE_URL
from models import Compound, Phase
from services.json_client import JsonClient
from utils.url_utils import compound_json_url, extract_image_url

log = logging.getLogger("nawy.compound_scraper")


class CompoundScraper:
    """
    Fetches compound-level data from the Nawy Next.js API.
    Returns a Compound model with images and phases populated.
    """

    def __init__(self, json_client: JsonClient, build_id: str):
        self._client   = json_client
        self._build_id = build_id

    async def scrape(self, compound_slug: str) -> Optional[Compound]:
        """
        Fetch a compound page JSON and return a populated Compound.
        Returns None if the page cannot be fetched.
        """
        url  = compound_json_url(BASE_URL, self._build_id, compound_slug)
        data = await self._client.get(url)

        if not data:
            log.warning(f"No data for compound: {compound_slug}")
            return None

        # Next.js wraps everything inside pageProps
        raw = data.get("pageProps", {}).get("compound") or data.get("compound")
        if not raw:
            log.warning(f"Unexpected JSON shape for: {compound_slug}")
            return None


        # if parentCompound is set, this is a phase inside another project
        # it will be scraped correctly when we process its parent — skip here
        if raw.get("parentCompound"):
            log.info(f"  [phase] {compound_slug} is a phase — skipping top-level")
            return None


        name   = raw.get("name") or raw.get("displayName") or compound_slug
        images = self._parse_images(raw)
        phases = self._parse_phases(raw)

        log.info(f"  {name}: {len(images)} images | {len(phases)} phase(s)")

        return Compound(
            slug=compound_slug,
            name=name,
            images=images,
            phases=phases,
        )

    async def scrape_phase(self, phase_meta: Phase) -> Phase:
        """
        A phase in Nawy is itself a compound — it has its own JSON endpoint.
        This enriches the Phase stub (from parent compound) with full images.
        """
        url  = compound_json_url(BASE_URL, self._build_id, phase_meta.slug)
        data = await self._client.get(url)

        # start with thumbnail we already have from parent compound
        images = list(phase_meta.images)

        if data:
            raw          = data.get("pageProps", {}).get("compound") or data.get("compound") or {}
            phase_images = self._parse_images(raw)
            # merge without duplicates
            seen = set(images)
            for img in phase_images:
                if img not in seen:
                    images.append(img)
                    seen.add(img)

        return Phase(
            slug=phase_meta.slug,
            name=phase_meta.name,
            images=images,
            unit_slugs=phase_meta.unit_slugs,
        )

    # ── Private helpers ──────────────────────────────────────────

    @staticmethod
    def _parse_images(raw: dict) -> list[str]:
        """Extract all image URLs including the master plan."""
        images: list[str] = []
        seen:   set[str]  = set()

        for item in (raw.get("images") or []):
            url = extract_image_url(item)
            if url and url not in seen:
                seen.add(url)
                images.append(url)

        # master plan is a separate field, add it at the end
        master = raw.get("masterPlan")
        if master and master not in seen:
            images.append(master)

        return images

    @staticmethod
    def _parse_phases(raw: dict) -> list[Phase]:
        """Extract Phase stubs from compound JSON (slug, name, thumbnail only)."""
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