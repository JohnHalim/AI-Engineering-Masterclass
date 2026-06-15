import logging
from typing import Literal
from config import PROGRESS_FILE
from utils.file_utils import load_json, save_json

log = logging.getLogger("nawy.checkpoint")

Status = Literal["done", "failed", "error", "skipped"]


class CheckpointService:
    """
    Tracks completed compounds in progress.json.
    Persists to disk after every update so crashes lose no progress.
    """

    def __init__(self):
        self._data: dict[str, Status] = load_json(PROGRESS_FILE) or {}
        done   = sum(1 for v in self._data.values() if v == "done")
        errors = sum(1 for v in self._data.values() if v in ("failed", "error"))
        log.info(f"Checkpoint loaded: {done} done, {errors} errors")

    def is_done(self, slug: str) -> bool:
        """Return True if this compound was already completed."""
        return self._data.get(slug) == "done"

    def is_skipped(self, slug: str) -> bool:
        """Return true if this compound is a phase in another compound"""
        return self._data.get(slug) == "skipped"
    
    def mark(self, slug: str, status: Status) -> None:
        """Save status for a compound and immediately write to disk."""
        self._data[slug] = status
        save_json(PROGRESS_FILE, self._data)

    def summary(self) -> tuple[int, int]:
        """Return (done_count, error_count)."""
        done   = sum(1 for v in self._data.values() if v == "done")
        skipped = sum(1 for v in self._data.values() if v == "skipped")
        errors = sum(1 for v in self._data.values() if v in ("failed", "error"))
        return done, skipped,  errors