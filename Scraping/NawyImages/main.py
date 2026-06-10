"""
main.py  —  Nawy Image Scraper  (entry point)
══════════════════════════════════════════════
Orchestrates the three phases:

  Phase 1  →  SearchScraper scrolls nawy.com/search and collects
               every compound slug.  (cached to slugs_cache.json)

  Phase 2  →  For each compound slug:
               • CompoundScraper fetches compound images + phases
               • PropertyScraper fetches unit slugs + unit images
               • Phase images and phase-unit images are fetched too

  Phase 3  →  ImageDownloader saves everything to disk under output/

Folder layout produced:
  output/
    <Compound Name>/
      cover/                ← compound gallery + master plan
      phases/
        <Phase Name>/
          cover/            ← phase gallery
          units/
            <unit-slug>/
              images/
              floor_plans/
      units/                ← units not belonging to any phase
        <unit-slug>/
          images/
          floor_plans/

Resume support:
  progress.json tracks completed compounds.
  Re-running main.py skips already-done compounds automatically.

Usage:
  pip install playwright httpx aiofiles
  playwright install chromium
  python main.py
"""

import asyncio
import logging
import sys
from pathlib import Path

import httpx

from config import (
    OUTPUT_DIR, LOG_FILE, HTTP_HEADERS,
    BASE_URL, POLITENESS_DELAY_S,
)
from scrapers  import SearchScraper, CompoundScraper, PropertyScraper
from services  import BuildIDResolver, JsonClient, ImageDownloader, CheckpointService
from utils     import safe_name


# ── Logging setup ──────────────────────────────────────────────────────────

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

log = logging.getLogger("nawy")


# ── Compound processor ─────────────────────────────────────────────────────

class CompoundProcessor:
    """
    Processes one compound end-to-end:
      fetch data  →  download compound images
                  →  for each phase: download phase images + phase units
                  →  for remaining units: download unit images
    """

    def __init__(
        self,
        compound_scraper: CompoundScraper,
        property_scraper: PropertyScraper,
        downloader:        ImageDownloader,
        root:              Path,
    ):
        self._compounds  = compound_scraper
        self._properties = property_scraper
        self._dl         = downloader
        self._root       = root

    async def process(self, compound_slug: str) -> bool:
        """
        Full pipeline for one compound.
        Returns True on success, False if compound data could not be fetched.
        """
        # ── Fetch compound ─────────────────────────────────────────
        compound = await self._compounds.scrape(compound_slug)
        if not compound:
            return False

        compound_folder = self._root / safe_name(compound.name)
        compound_folder.mkdir(parents=True, exist_ok=True)

        # ── Compound-level images ──────────────────────────────────
        await self._dl.download_batch(
            compound.images,
            compound_folder / "cover",
            label=compound.name,
        )

        # ── Fetch unit slugs for the whole compound ────────────────
        all_unit_slugs = await self._properties.get_unit_slugs(compound_slug)
        log.info(f"  {compound.name}: {len(all_unit_slugs)} unit(s) total")

        # ── Phases ────────────────────────────────────────────────
        phase_unit_slugs: set[str] = set()

        for phase_meta in compound.phases:
            await asyncio.sleep(POLITENESS_DELAY_S)

            # Enrich phase with its full image list
            phase = await self._compounds.scrape_phase(phase_meta)

            # Fetch unit slugs specific to this phase
            phase_unit_slugs_list = await self._properties.get_unit_slugs(phase.slug)
            phase_unit_slugs.update(phase_unit_slugs_list)

            phase_folder = compound_folder / "phases" / safe_name(phase.name)
            phase_folder.mkdir(parents=True, exist_ok=True)

            # Phase cover images
            await self._dl.download_batch(
                phase.images,
                phase_folder / "cover",
                label=f"phase:{phase.name}",
            )

            # Phase units
            await self._process_units(
                phase_unit_slugs_list,
                compound_slug,
                phase_folder / "units",
            )

        # ── Standalone units (not in any phase) ───────────────────
        standalone = [s for s in all_unit_slugs if s not in phase_unit_slugs]
        await self._process_units(standalone, compound_slug, compound_folder / "units")

        return True

    async def _process_units(
        self,
        unit_slugs: list[str],
        compound_slug: str,
        units_folder: Path,
    ) -> None:
        """Download images and floor plans for a list of units."""
        for unit_slug in unit_slugs:
            await asyncio.sleep(POLITENESS_DELAY_S)

            unit = await self._properties.scrape(compound_slug, unit_slug)

            unit_folder = units_folder / safe_name(unit.slug)

            if unit.images:
                await self._dl.download_batch(
                    unit.images,
                    unit_folder / "images",
                    label=f"unit:{unit.slug}",
                )
            if unit.floor_plans:
                await self._dl.download_batch(
                    unit.floor_plans,
                    unit_folder / "floor_plans",
                    label=f"fp:{unit.slug}",
                )


# ── Main ───────────────────────────────────────────────────────────────────

async def main() -> None:
    _setup_logging()

    root = Path(OUTPUT_DIR)
    root.mkdir(exist_ok=True)

    # ── Phase 1: collect all compound slugs ───────────────────────
    log.info("═" * 60)
    log.info("PHASE 1  —  Collecting compound slugs")
    log.info("═" * 60)

    search_scraper = SearchScraper()
    slugs          = await search_scraper.get_compound_slugs()

    log.info(f"Total compounds to process: {len(slugs)}\n")

    # ── Shared services ───────────────────────────────────────────
    checkpoint = CheckpointService()

    async with httpx.AsyncClient(
        headers=HTTP_HEADERS,
        follow_redirects=True,
    ) as http:

        # Resolve Next.js BUILD_ID (once, cached in memory)
        build_id_resolver = BuildIDResolver()
        build_id          = await build_id_resolver.resolve(http)

        json_client = JsonClient(http)
        downloader  = ImageDownloader(http)
        processor   = CompoundProcessor(
            compound_scraper = CompoundScraper(json_client, build_id),
            property_scraper = PropertyScraper(json_client, build_id),
            downloader       = downloader,
            root             = root,
        )

        # ── Phase 2 + 3: process each compound ────────────────────
        log.info("═" * 60)
        log.info("PHASE 2+3  —  Scraping + downloading")
        log.info("═" * 60)

        for i, slug in enumerate(slugs, 1):
            log.info(f"\n[{i}/{len(slugs)}]  {slug}")

            if checkpoint.is_done(slug):
                log.info("  [skip] already completed")
                continue

            try:
                success = await processor.process(slug)
                checkpoint.mark(slug, "done" if success else "failed")
            except Exception as exc:
                log.error(f"  Unhandled error for {slug}: {exc}", exc_info=True)
                checkpoint.mark(slug, "error")

            await asyncio.sleep(POLITENESS_DELAY_S)

    # ── Summary ───────────────────────────────────────────────────
    done, errors = checkpoint.summary()
    log.info("\n" + "═" * 60)
    log.info(f"  Finished.  {done} done  |  {errors} errors")
    log.info(f"  Output: {root.resolve()}")
    log.info("═" * 60)


if __name__ == "__main__":
    asyncio.run(main())
