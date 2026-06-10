# ── Paths ──────────────────────────────────────────────
OUTPUT_DIR       = "output"
SLUGS_CACHE_FILE = "slugs_cache.json"
PROGRESS_FILE    = "progress.json"
LOG_FILE         = "scraper.log"

# ── Nawy URLs ──────────────────────────────────────────
BASE_URL   = "https://www.nawy.com"
SEARCH_URL = "https://www.nawy.com/search"

# ── Browser scroll (Phase 1) ───────────────────────────
SCROLL_PAUSE_MS    = 1500
SCROLL_STALE_LIMIT = 5

# ── HTTP client ────────────────────────────────────────
REQUEST_TIMEOUT    = 30
RETRY_ATTEMPTS     = 3
RETRY_DELAY_S      = 2
POLITENESS_DELAY_S = 0.3

# ── Downloader ─────────────────────────────────────────
DOWNLOAD_CONCURRENCY = 5

# ── Units ──────────────────────────────────────────────
UNITS_PAGE_SIZE = 100

# ── HTTP headers ───────────────────────────────────────
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nawy.com/",
    "Accept-Language": "en-US,en;q=0.9",
}