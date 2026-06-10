import json, re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

def safe_name(text: str) -> str:
    text = unquote(str(text))
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    return text[:120] or "unnamed"
    

def load_json(path: str) -> Optional[Any]:
    p = Path(path)
    if not p.exists:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    

def save_json(path: str, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")