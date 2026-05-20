"""
Nawy.com Full Scraper
=====================
Hierarchy: Developer → Project (Compound) → Phase (optional) → Unit
Stores everything in PostgreSQL.

Architecture notes (from live inspection):
- Nawy is a Server-Side Rendered (SSR) Next.js site — pages render as full HTML.
  This means we can use requests + BeautifulSoup without needing Playwright/Selenium.
  However, unit listing cards are loaded dynamically via client-side JS, so we need
  Playwright for pages that show unit cards (compound listing pages).
- The developer list page is fully static HTML — no JS needed.
- Compound pages are SSR but unit cards require JS execution.

Strategy:
  Step 1 → GET /developer  → parse all developer slugs from static HTML
  Step 2 → For each developer → GET /developer/{slug} → parse compound links
  Step 3 → For each compound → use Playwright to render JS, scrape:
             - Is it a parent project with phases? If yes, collect phase links.
             - If no phases, scrape units directly.
  Step 4 → For each phase compound → scrape units with Playwright
  Step 5 → For each unit card → click / navigate to unit detail page → scrape all fields
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import asyncpg
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, BrowserContext

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "https://www.nawy.com"
CONCURRENCY = 3          # parallel compound scrapers (be polite)
REQUEST_DELAY = 1.5      # seconds between page loads per worker
HEADLESS = True

DB_DSN = "postgresql://user:password@localhost:5432/nawy_db"
# ↑ Change this to your actual PostgreSQL connection string

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("nawy_scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("nawy")

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Developer:
    id: int                      # numeric ID extracted from URL slug
    name: str
    slug: str                    # e.g. "6-mountain-view"
    url: str

@dataclass
class Compound:
    id: int
    name: str
    slug: str
    url: str
    developer_id: int
    developer_name: str
    area: Optional[str] = None
    is_phase: bool = False       # True when this compound is a phase of a parent
    parent_compound_id: Optional[int] = None
    parent_compound_name: Optional[str] = None

@dataclass
class Unit:
    compound_id: int
    compound_name: str
    developer_id: int
    developer_name: str
    phase_compound_id: Optional[int]     # None when project has no phases
    phase_name: Optional[str]            # None when project has no phases
    has_phases: bool                     # explicit flag per your requirement
    unit_type: Optional[str] = None      # Apartment, Villa, Townhouse, …
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    area_sqm: Optional[float] = None
    price: Optional[float] = None
    currency: Optional[str] = None       # EGP / USD / EUR / …
    down_payment_pct: Optional[float] = None
    installment_years: Optional[int] = None
    installment_plan_desc: Optional[str] = None
    unit_url: Optional[str] = None
    nawy_unit_id: Optional[str] = None

# ── PostgreSQL helpers ────────────────────────────────────────────────────────

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS developers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    url             TEXT NOT NULL,
    scraped_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS compounds (
    id                      INTEGER PRIMARY KEY,
    name                    TEXT NOT NULL,
    slug                    TEXT UNIQUE NOT NULL,
    url                     TEXT NOT NULL,
    developer_id            INTEGER REFERENCES developers(id),
    developer_name          TEXT,
    area                    TEXT,
    is_phase                BOOLEAN DEFAULT FALSE,
    parent_compound_id      INTEGER,
    parent_compound_name    TEXT,
    scraped_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS units (
    id                      SERIAL PRIMARY KEY,
    compound_id             INTEGER REFERENCES compounds(id),
    compound_name           TEXT,
    developer_id            INTEGER REFERENCES developers(id),
    developer_name          TEXT,
    phase_compound_id       INTEGER,          -- NULL = project has no phases
    phase_name              TEXT,             -- NULL = project has no phases
    has_phases              BOOLEAN NOT NULL, -- explicit: TRUE even if we store the parent row
    unit_type               TEXT,
    bedrooms                INTEGER,
    bathrooms               INTEGER,
    area_sqm                NUMERIC(10,2),
    price                   NUMERIC(18,2),
    currency                VARCHAR(10),      -- EGP / USD / EUR etc.
    down_payment_pct        NUMERIC(6,2),
    installment_years       INTEGER,
    installment_plan_desc   TEXT,
    unit_url                TEXT,
    nawy_unit_id            TEXT,
    scraped_at              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (nawy_unit_id)   -- prevent duplicate rows on re-runs
);
"""

async def init_db(dsn: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn)
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
    log.info("Database tables ready.")
    return pool

async def upsert_developer(pool, dev: Developer):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO developers (id, name, slug, url)
            VALUES ($1,$2,$3,$4)
            ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, url=EXCLUDED.url
        """, dev.id, dev.name, dev.slug, dev.url)

async def upsert_compound(pool, comp: Compound):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO compounds
              (id, name, slug, url, developer_id, developer_name, area,
               is_phase, parent_compound_id, parent_compound_name)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (id) DO UPDATE SET
              name=EXCLUDED.name, url=EXCLUDED.url,
              area=EXCLUDED.area,
              is_phase=EXCLUDED.is_phase,
              parent_compound_id=EXCLUDED.parent_compound_id,
              parent_compound_name=EXCLUDED.parent_compound_name
        """, comp.id, comp.name, comp.slug, comp.url,
             comp.developer_id, comp.developer_name, comp.area,
             comp.is_phase, comp.parent_compound_id, comp.parent_compound_name)

async def insert_unit(pool, u: Unit):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO units
              (compound_id, compound_name, developer_id, developer_name,
               phase_compound_id, phase_name, has_phases,
               unit_type, bedrooms, bathrooms, area_sqm,
               price, currency,
               down_payment_pct, installment_years, installment_plan_desc,
               unit_url, nawy_unit_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
            ON CONFLICT (nawy_unit_id) DO NOTHING
        """,
        u.compound_id, u.compound_name, u.developer_id, u.developer_name,
        u.phase_compound_id, u.phase_name, u.has_phases,
        u.unit_type, u.bedrooms, u.bathrooms, u.area_sqm,
        u.price, u.currency,
        u.down_payment_pct, u.installment_years, u.installment_plan_desc,
        u.unit_url, u.nawy_unit_id)

# ── Step 1: Scrape all developers from /developer ────────────────────────────

def parse_developers(html: str) -> list[Developer]:
    """
    The /developer page is pure SSR HTML. Developer cards look like:
      <a href="/developer/6-mountain-view">Mountain View<br>50 Compounds...</a>
    We extract the numeric ID + name from the href and link text.
    """
    soup = BeautifulSoup(html, "html.parser")
    devs = []
    seen_ids = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # match /developer/123-some-name  (not /developer alone)
        m = re.match(r"^/developer/(\d+)-(.+)$", href)
        if not m:
            continue
        dev_id = int(m.group(1))
        if dev_id in seen_ids:
            continue
        seen_ids.add(dev_id)

        slug = f"{m.group(1)}-{m.group(2)}"
        # Name: first text node inside the <a>, strip whitespace
        raw_text = a.get_text(" ", strip=True)
        # Remove trailing stats like "50 Compounds 1572 Properties..."
        name = re.split(r"\d+\s+Compound", raw_text)[0].strip()
        name = name.lstrip("logo").strip()  # images render as "logo" text

        devs.append(Developer(
            id=dev_id,
            name=name,
            slug=slug,
            url=urljoin(BASE_URL, href),
        ))

    log.info(f"Found {len(devs)} developers.")
    return devs

# ── Step 2: Scrape compound links from a developer page ──────────────────────

def parse_compounds_from_developer(html: str, developer: Developer) -> list[Compound]:
    """
    Each developer page lists compounds as:
      <a href="/compound/996-aliva-mountain-view-mostakbal-city">Compound Name</a>
    Some cards include the area in the breadcrumb, but we can also derive it later.
    """
    soup = BeautifulSoup(html, "html.parser")
    compounds = []
    seen_ids = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.match(r"^/compound/(\d+)-(.+)$", href)
        if not m:
            continue
        cid = int(m.group(1))
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        slug = f"{m.group(1)}-{m.group(2)}"
        name = a.get_text(" ", strip=True)
        name = re.split(r"\d+\s+Propert", name)[0].strip()
        name = name.lstrip("logo").strip()
        if not name:
            name = slug.split("-", 1)[-1].replace("-", " ").title()

        compounds.append(Compound(
            id=cid,
            name=name,
            slug=slug,
            url=urljoin(BASE_URL, href),
            developer_id=developer.id,
            developer_name=developer.name,
        ))

    log.info(f"  Developer '{developer.name}' → {len(compounds)} compounds found.")
    return compounds

# ── Step 3: Scrape a compound page (JS-rendered) ─────────────────────────────

async def scrape_compound_page(page: Page, compound: Compound, pool) -> tuple[list[Compound], list[Unit]]:
    """
    Navigate to the compound page. Detect:
      A) Has phases section → collect phase URLs, return them as child Compound objects
      B) No phases → scrape unit cards directly
    Returns (phases, units). Exactly one of them will be non-empty.
    """
    await page.goto(compound.url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(REQUEST_DELAY)

    # Wait for main content
    try:
        await page.wait_for_selector("h1", timeout=15000)
    except Exception:
        log.warning(f"  Timeout waiting for h1 on {compound.url}")

    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")

    # ── Detect phases section ────────────────────────────────────────────────
    # Nawy renders a "Phases" heading followed by phase cards
    # Each phase card is an <a href="/compound/{id}-{slug}">
    phases: list[Compound] = []
    phase_section = soup.find(string=re.compile(r"^Phases$", re.I))
    if phase_section:
        # Walk siblings/parent to find phase links
        container = phase_section.find_parent()
        while container and container.name not in ("section", "div"):
            container = container.find_parent()

        if container:
            for a in container.find_all("a", href=True):
                m = re.match(r"^/compound/(\d+)-(.+)$", a["href"])
                if not m:
                    continue
                phase_id = int(m.group(1))
                if phase_id == compound.id:
                    continue
                slug = f"{m.group(1)}-{m.group(2)}"
                phase_name = a.get_text(" ", strip=True)
                phase_name = re.sub(r"\d+\s+Propert.*", "", phase_name).strip()
                if not phase_name:
                    phase_name = slug.split("-", 1)[-1].replace("-", " ").title()

                phases.append(Compound(
                    id=phase_id,
                    name=phase_name,
                    slug=slug,
                    url=urljoin(BASE_URL, a["href"]),
                    developer_id=compound.developer_id,
                    developer_name=compound.developer_name,
                    is_phase=True,
                    parent_compound_id=compound.id,
                    parent_compound_name=compound.name,
                ))

    if phases:
        log.info(f"  Compound '{compound.name}' has {len(phases)} phases.")
        return phases, []

    # ── No phases: scrape units from this page ───────────────────────────────
    units = await scrape_units_from_page(page, soup, compound, compound, has_phases=False, pool=pool)
    return [], units

# ── Step 4: Scrape unit cards from a compound/phase page ─────────────────────

async def scrape_units_from_page(
    page: Page,
    soup: BeautifulSoup,
    compound: Compound,          # the parent project (may equal phase_compound)
    phase_compound: Compound,    # the actual compound whose page we're on
    has_phases: bool,
    pool,
) -> list[Unit]:
    """
    Unit cards are rendered client-side. Each card has:
      - Unit type (Apartment, Villa, etc.)
      - Bedrooms count
      - Bathrooms count
      - Area in sqm
      - Price with currency symbol (EGP / $)
      - Link to unit detail page

    We paginate through all pages using the Next button.
    """
    all_units = []
    page_num = 1

    while True:
        log.info(f"    Scraping units — page {page_num} of '{phase_compound.name}'")
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        units = parse_unit_cards(
            soup,
            compound=compound,
            phase_compound=phase_compound,
            has_phases=has_phases,
        )
        all_units.extend(units)

        # Save to DB immediately (streaming insert, avoids memory bloat)
        for u in units:
            await insert_unit(pool, u)

        # Try to click "Next" for pagination
        next_btn = await page.query_selector("button:has-text('Next'), a:has-text('Next'), [aria-label='Next page']")
        if not next_btn:
            break
        is_disabled = await next_btn.get_attribute("disabled")
        if is_disabled is not None:
            break

        await next_btn.click()
        await asyncio.sleep(REQUEST_DELAY)
        page_num += 1

    log.info(f"    → {len(all_units)} units scraped from '{phase_compound.name}'.")
    return all_units

# ── Parse unit cards from rendered HTML ──────────────────────────────────────

CURRENCY_MAP = {
    "EGP": "EGP",
    "LE":  "EGP",
    "جنيه": "EGP",
    "$":   "USD",
    "USD": "USD",
    "€":   "EUR",
    "EUR": "EUR",
    "AED": "AED",
    "SAR": "SAR",
}

def detect_currency(text: str) -> tuple[Optional[str], Optional[float]]:
    """
    Given a price string like '5,750,000 EGP' or '$1,200,000',
    returns (currency_code, numeric_value).
    Handles EGP, USD ($), EUR (€) and others.
    """
    text = text.strip()

    # Remove commas from numbers
    cleaned = text.replace(",", "")

    # Try to detect currency symbol/code
    currency = None
    for symbol, code in CURRENCY_MAP.items():
        if symbol in text:
            currency = code
            break

    # Extract numeric value
    numbers = re.findall(r"[\d.]+", cleaned)
    value = float(numbers[0]) if numbers else None

    return currency, value

def parse_unit_cards(soup: BeautifulSoup, compound: Compound, phase_compound: Compound, has_phases: bool) -> list[Unit]:
    """
    Nawy unit cards typically look like:
      <div class="property-card"> or similar container
        <h3>Apartment</h3>
        <span>3 Beds</span>
        <span>2 Baths</span>
        <span>150 m²</span>
        <span>5,750,000 EGP</span>
        <a href="/property/...">View</a>
      </div>

    Since the exact class names can change, we use heuristic text matching.
    """
    units = []

    # Find all anchor tags that link to /property/ pages
    property_links = soup.find_all("a", href=re.compile(r"^/property/\d+"))

    # Also try cards that contain price + area info even without property links
    # Fall back to looking for any block with both "sqm"/"m²" and a price pattern
    if not property_links:
        # Try broader card detection
        property_links = soup.find_all("a", href=re.compile(r"/property"))

    seen_urls = set()

    for a in property_links:
        href = a.get("href", "")
        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Extract unit ID from URL
        uid_m = re.search(r"/property/(\d+)", href)
        nawy_unit_id = uid_m.group(1) if uid_m else None

        # Walk up to the card container
        card = a
        for _ in range(6):
            parent = card.find_parent()
            if parent is None:
                break
            # Stop at a container that has meaningful content
            text = parent.get_text(" ", strip=True)
            if len(text) > 80 and any(kw in text.lower() for kw in ["bed", "bath", "sqm", "m²", "egp", "$"]):
                card = parent
                break
            card = parent

        card_text = card.get_text(" ", strip=True)

        unit = Unit(
            compound_id=compound.id,
            compound_name=compound.name,
            developer_id=compound.developer_id,
            developer_name=compound.developer_name,
            phase_compound_id=phase_compound.id if has_phases else None,
            phase_name=phase_compound.name if has_phases else None,
            has_phases=has_phases,
            unit_url=full_url,
            nawy_unit_id=nawy_unit_id,
        )

        # Unit type — first word / short label near the card heading
        for tag in card.find_all(["h2", "h3", "h4", "strong", "span", "p"]):
            t = tag.get_text(strip=True)
            if t in ("Apartment", "Villa", "Townhouse", "Duplex", "Chalet",
                     "Studio", "Penthouse", "IVilla", "Twin House",
                     "Standalone Villa", "Office", "Clinic", "Retail"):
                unit.unit_type = t
                break

        # Bedrooms
        bed_m = re.search(r"(\d+)\s*(?:Bed|BR|bedroom)", card_text, re.I)
        if bed_m:
            unit.bedrooms = int(bed_m.group(1))

        # Bathrooms
        bath_m = re.search(r"(\d+)\s*(?:Bath|bathroom)", card_text, re.I)
        if bath_m:
            unit.bathrooms = int(bath_m.group(1))

        # Area in sqm — matches "150 sqm" or "150 m²" or "150m²"
        area_m = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:sqm|m²|sq\.m)", card_text, re.I)
        if area_m:
            unit.area_sqm = float(area_m.group(1).replace(",", ""))

        # Price + currency
        # Pattern: digits (with commas) followed by EGP/USD/$ or preceded by $
        price_m = re.search(
            r"([\$€£]?)\s*([\d,]+(?:\.\d+)?)\s*(EGP|USD|EUR|AED|SAR|LE|جنيه)?",
            card_text,
        )
        if price_m:
            pre_sym  = price_m.group(1)
            num_str  = price_m.group(2)
            post_sym = price_m.group(3) or ""
            combined = (pre_sym + " " + post_sym).strip()
            currency, price_val = detect_currency(combined + " " + num_str)
            if price_val and price_val > 10000:  # sanity — skip tiny numbers
                unit.price = price_val
                unit.currency = currency or "EGP"  # default to EGP for Egypt market

        units.append(unit)

    return units

# ── Playwright browser worker ─────────────────────────────────────────────────

async def browser_worker(
    worker_id: int,
    compound_queue: asyncio.Queue,
    pool,
    context: BrowserContext,
):
    page = await context.new_page()

    # Block images, fonts, and media to speed things up
    await page.route("**/*.{png,jpg,jpeg,webp,gif,svg,woff,woff2,ttf,mp4,mp3}", lambda r: r.abort())

    while True:
        try:
            compound: Compound = compound_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        log.info(f"[Worker {worker_id}] Processing compound: {compound.name} ({compound.url})")

        try:
            phases, units = await scrape_compound_page(page, compound, pool)

            # Save compound itself
            await upsert_compound(pool, compound)

            # If it has phases: queue each phase for scraping
            for ph in phases:
                await upsert_compound(pool, ph)
                # Scrape phase units immediately (within same worker)
                await page.goto(ph.url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(REQUEST_DELAY)
                try:
                    await page.wait_for_selector("h1", timeout=15000)
                except Exception:
                    pass
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                phase_units = await scrape_units_from_page(
                    page, soup,
                    compound=compound,        # parent project
                    phase_compound=ph,        # the phase
                    has_phases=True,
                    pool=pool,
                )
                log.info(f"  Phase '{ph.name}': {len(phase_units)} units saved.")

        except Exception as e:
            log.error(f"  ERROR on compound {compound.name}: {e}", exc_info=True)

        compound_queue.task_done()

    await page.close()

# ── Main orchestrator ─────────────────────────────────────────────────────────

async def main():
    # ── Init DB
    pool = await init_db(DB_DSN)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 800},
        )

        # ── Step 1: Get all developers (static HTML, no JS needed)
        log.info("Step 1: Fetching developer list...")
        dev_page = await context.new_page()
        await dev_page.goto(f"{BASE_URL}/developer", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        dev_html = await dev_page.content()
        await dev_page.close()

        developers = parse_developers(dev_html)
        for dev in developers:
            await upsert_developer(pool, dev)

        # ── Step 2: Get all compounds from each developer
        log.info("Step 2: Fetching compounds from each developer...")
        all_compounds: list[Compound] = []
        comp_page = await context.new_page()

        for dev in developers:
            log.info(f"  Fetching compounds for: {dev.name}")
            await comp_page.goto(dev.url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(REQUEST_DELAY)
            html = await comp_page.content()
            compounds = parse_compounds_from_developer(html, dev)
            all_compounds.extend(compounds)
            time.sleep(0.5)

        await comp_page.close()
        log.info(f"Total compounds to scrape: {len(all_compounds)}")

        # ── Step 3+4: Scrape each compound concurrently
        log.info("Step 3+4: Scraping compound pages and units...")
        queue: asyncio.Queue[Compound] = asyncio.Queue()
        for comp in all_compounds:
            await queue.put(comp)

        workers = [
            asyncio.create_task(
                browser_worker(i, queue, pool, context)
            )
            for i in range(CONCURRENCY)
        ]
        await asyncio.gather(*workers)

        await browser.close()

    await pool.close()
    log.info("✅ Scraping complete.")

if __name__ == "__main__":
    asyncio.run(main())
