import asyncio
import logging
import sys
from pathlib import Path

import httpx

from config   import OUTPUT_DIR, LOG_FILE, HTTP_HEADERS, BASE_URL, POLITENESS_DELAY_S
from models   import Compound, Phase, Property
from services import JsonClient, BuildIDResolver, ImageDownloader, CheckpointService
from scrapers import SearchScraper, CompoundScraper, PropertyScraper
from utils    import safe_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nawy")


# ─────────────────────────────────────────────────────────────────
#  CompoundProcessor  —  handles one compound end to end
# ─────────────────────────────────────────────────────────────────

class CompoundProcessor:
    """
    For one compound slug:
      1. Fetch compound images → download to <compound>/cover/
      2. For each phase:
           fetch phase images   → download to <compound>/phases/<phase>/cover/
           fetch phase units    → download to <compound>/phases/<phase>/units/<unit>/
      3. For standalone units (not in any phase):
           fetch unit images    → download to <compound>/units/<unit>/images/
           fetch floor plans    → download to <compound>/units/<unit>/floor_plans/
    """

    def __init__(
        self,
        compound_scraper: CompoundScraper,
        property_scraper: PropertyScraper,
        downloader:       ImageDownloader,
        root:             Path,
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

        # ── fetch compound ────────────────────────────────────────
        compound = await self._compounds.scrape(compound_slug)
        if not compound:
            return False

        compound_folder = self._root / safe_name(compound.name)
        compound_folder.mkdir(parents=True, exist_ok=True)

        # ── compound cover images ─────────────────────────────────
        await self._dl.download_batch(
            compound.images,
            compound_folder / "cover",
            label=compound.name,
        )

        # ── fetch all unit slugs for this compound ────────────────
        all_unit_slugs = await self._properties.get_unit_slugs(compound_slug)
        log.info(f"  {compound.name}: {len(all_unit_slugs)} unit(s) | {len(compound.phases)} phase(s)")

        # ── phases ────────────────────────────────────────────────
        phase_unit_slugs: set[str] = set()

        for phase_meta in compound.phases:
            await asyncio.sleep(POLITENESS_DELAY_S)

            # enrich phase with full image list
            phase = await self._compounds.scrape_phase(phase_meta)

            # get unit slugs specific to this phase
            p_unit_slugs = await self._properties.get_unit_slugs(phase.slug)
            phase_unit_slugs.update(p_unit_slugs)

            phase_folder = compound_folder / "phases" / safe_name(phase.name)
            phase_folder.mkdir(parents=True, exist_ok=True)

            # phase cover images
            await self._dl.download_batch(
                phase.images,
                phase_folder / "cover",
                label=f"phase:{phase.name}",
            )

            # phase units
            await self._process_units(
                slugs           = p_unit_slugs,
                compound_slug   = compound_slug,
                units_folder    = phase_folder / "units",
            )

        # ── standalone units (not belonging to any phase) ─────────
        standalone = [s for s in all_unit_slugs if s not in phase_unit_slugs]
        await self._process_units(
            slugs         = standalone,
            compound_slug = compound_slug,
            units_folder  = compound_folder / "units",
        )

        return True

    async def _process_units(
        self,
        slugs:         list[str] | set[str],
        compound_slug: str,
        units_folder:  Path,
    ) -> None:
        """Download images and floor plans for a list of unit slugs."""
        for unit_slug in slugs:
            await asyncio.sleep(POLITENESS_DELAY_S)

            unit = await self._properties.scrape(compound_slug, unit_slug)

            unit_folder = units_folder / safe_name(unit.slug)
            # unit_id     = unit.slug.split("-")[0]
            # unit_folder = units_folder / unit_id

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


# ─────────────────────────────────────────────────────────────────
#  main
# ─────────────────────────────────────────────────────────────────

async def main() -> None:
    root = Path(OUTPUT_DIR)
    root.mkdir(exist_ok=True)

    # ── Phase 1: collect all compound slugs ───────────────────────
    log.info("═" * 60)
    log.info("PHASE 1  —  Collecting compound slugs")
    log.info("═" * 60)

    async with httpx.AsyncClient(headers=HTTP_HEADERS, follow_redirects=True) as http:

        search_scraper = SearchScraper(http)
        slugs          = await search_scraper.get_compound_slugs()
#############################################################################################################
        # slugs = ["742-stei8ht"]  # TEST: compound with 4 phases
#############################################################################################################
        log.info(f"Total compounds: {len(slugs)}")

        # ── shared services ───────────────────────────────────────
        build_id_resolver = BuildIDResolver()
        build_id          = await build_id_resolver.resolve(http)

        json_client = JsonClient(http)
        downloader  = ImageDownloader(http)
        checkpoint  = CheckpointService()

        processor = CompoundProcessor(
            compound_scraper = CompoundScraper(json_client, build_id),
            property_scraper = PropertyScraper(json_client, build_id),
            downloader       = downloader,
            root             = root,
        )

        # ── Phase 2 + 3: scrape + download ───────────────────────
        log.info("\n" + "═" * 60)
        log.info("PHASE 2+3  —  Scraping and downloading")
        log.info("═" * 60 + "\n")

        for i, slug in enumerate(slugs, 1):
            log.info(f"[{i}/{len(slugs)}]  {slug}")

            if checkpoint.is_done(slug):
                log.info("  [skip] already completed")
                continue

            try:
                success = await processor.process(slug)
                if success:
                    checkpoint.mark(slug, "done")
                else:
                    # None returned = it's a phase, mark as skipped not failed
                    checkpoint.mark(slug, "skipped")
            except Exception as exc:
                log.error(f"  Unhandled error for {slug}: {exc}", exc_info=True)
                checkpoint.mark(slug, "error")

            await asyncio.sleep(POLITENESS_DELAY_S)

    # ── summary ───────────────────────────────────────────────────
    done, skipped, errors = checkpoint.summary()
    log.info("\n" + "═" * 60)
    log.info(f"  Finished.  {done} done  |  {skipped} phases skipped  |  {errors} errors")
    log.info(f"  Output: {root.resolve()}")
    log.info("═" * 60)


if __name__ == "__main__":
    asyncio.run(main())