"""
utils/url_utils.py
───────────────────
URL construction and filename helpers.
All functions are pure (no I/O, no side-effects).
"""

from urllib.parse import urlparse, unquote
from utils.file_utils import safe_name


# ── Next.js data URL builders ──────────────────────────────────────────────

def compound_json_url(base_url: str, build_id: str, compound_slug: str) -> str:
    """
    URL for the Next.js JSON data of a compound page.
    Example:
        https://www.nawy.com/_next/data/NU6jabI.../en/compound/742-stei8ht.json
    """
    return f"{base_url}/_next/data/{build_id}/en/compound/{compound_slug}.json"


def property_json_url(
    base_url: str,
    build_id: str,
    compound_slug: str,
    property_slug: str,
) -> str:
    """
    URL for the Next.js JSON data of a property/unit page.
    Example:
        https://www.nawy.com/_next/data/.../en/compound/742-stei8ht/property/12345-apt.json
    """
    return (
        f"{base_url}/_next/data/{build_id}/en/compound/{compound_slug}"
        f"/property/{property_slug}.json"
    )


def compound_page_url(base_url: str, compound_slug: str) -> str:
    """Human-readable compound page URL (used for the Referer header)."""
    return f"{base_url}/compound/{compound_slug}"


# ── Image filename derivation ──────────────────────────────────────────────

def filename_from_url(url: str, index: int) -> str:
    """
    Derive a clean filename from a CDN image URL.

    Nawy image URLs look like:
        https://prod-images.nawy.com/processed/compound_image/image/7923/high.webp

    We turn that into:  7923_high.webp
    Falls back to:      0001.webp  when the URL path is too short.
    """
    path  = urlparse(url).path                    # e.g. /processed/.../7923/high.webp
    parts = [p for p in path.split("/") if p]     # drop empty segments

    if len(parts) >= 2:
        # join last two path segments: "7923" + "high.webp" → "7923_high.webp"
        name = "_".join(parts[-2:])
    else:
        ext  = parts[-1].rsplit(".", 1)[-1] if parts else "webp"
        name = f"{index:04d}.{ext}"

    name = name.split("?")[0]   # strip any query string
    return safe_name(name)


# ── URL extraction from mixed API responses ────────────────────────────────

def extract_image_url(item) -> str:
    """
    Nawy API sometimes returns image URLs as plain strings,
    sometimes as objects like {"url": "...", "type": "gallery"}.
    This normalises both into a plain string.
    """
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return (
            item.get("url")
            or item.get("imageUrl")
            or item.get("src")
            or ""
        ).strip()
    return ""
