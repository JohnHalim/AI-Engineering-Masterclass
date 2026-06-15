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
    Derive a clean filename from an image URL.
    Uses only the last path segment (the actual filename).
    Falls back to index-based name if the URL has no clear filename.
    """
    path  = urlparse(url).path
    parts = [p for p in path.split("/") if p]

    if not parts:
        return f"{index:04d}.bin"

    # use only the last segment — the actual file name
    raw = parts[-1].split("?")[0]      # strip query string
    return safe_name(raw) or f"{index:04d}.bin"


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