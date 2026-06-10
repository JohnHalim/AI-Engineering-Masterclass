from urllib.parse import urlparse
from utils.file_utils import safe_name


def compound_json_url(base_url: str, build_id: str, compound_slug: str) -> str:
    """Build the Next.js JSON URL for a compound page."""
    return f"{base_url}/_next/data/{build_id}/en/compound/{compound_slug}.json"


def property_json_url(base_url: str, build_id: str, compound_slug: str, property_slug: str) -> str:
    """Build the Next.js JSON URL for a unit/property page."""
    return (
        f"{base_url}/_next/data/{build_id}/en/compound/{compound_slug}"
        f"/property/{property_slug}.json"
    )
    
    
def filename_from_url(url: str, index: int) -> str:
    """
    Derive a clean filename from a CDN image URL.
    https://.../image/7923/high.webp  →  7923_high.webp
    Falls back to 0001.webp if URL is too short.
    """
    path  = urlparse(url).path
    parts = [p for p in path.split("/") if p]   # remove empty segments

    if len(parts) >= 2:
        name = "_".join(parts[-2:])             # join last two: "7923_high.webp"
    else:
        ext  = parts[-1].rsplit(".", 1)[-1] if parts else "webp"
        name = f"{index:04d}.{ext}"

    name = name.split("?")[0]                   # strip any query string
    return safe_name(name)


def extract_image_url(item) -> str:
    """
    Nawy sometimes returns images as plain strings, sometimes as dicts.
    This normalises both into a plain URL string.
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