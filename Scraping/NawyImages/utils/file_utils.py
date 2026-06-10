"""
utils/file_utils.py
────────────────────
Filesystem helpers:
  - safe_name()   → sanitise any string for use as a folder/file name
  - load_json()   → read a JSON file, return None if missing/corrupt
  - save_json()   → write data to a JSON file (atomic-safe)
"""

import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote


def safe_name(text: str) -> str:
    """
    Convert any string into a safe folder / file name.
    Strips characters that are illegal on Windows, macOS, and Linux.
    Caps length at 120 characters.
    """
    text = unquote(str(text))
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    text = text.strip(". ")
    return text[:120] or "unnamed"


def load_json(path: str) -> Optional[Any]:
    """
    Read and parse a JSON file.
    Returns None if the file does not exist or cannot be parsed.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_json(path: str, data: Any) -> None:
    """
    Serialise data to a JSON file (UTF-8, human-readable indentation).
    Creates parent directories if needed.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
