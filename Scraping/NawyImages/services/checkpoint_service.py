"""
services/checkpoint_service.py
────────────────────────────────
Tracks which compounds have been fully processed.
Persists state to disk after every compound so the scraper
can be safely stopped and resumed at any time.

Status values:
    "done"    — compound fully processed
    "failed"  — compound JSON could not be fetched
    "error"   — unexpected exception during processing
"""

import logging
from typing import Literal

from config import PROGRESS_FILE
from utils.file_utils import load_json, save_json

log = logging.getLogger("nawy.checkpoint")

Status = Literal["done", "failed", "error"]


class CheckpointService:
    """
    Simple key-value progress tracker backed by a JSON file.

    Usage:
        ckpt = CheckpointService()
        if ckpt.is_done("742-stei8ht"):
            return
        # ... do work ...
        ckpt.mark("742-stei8ht", "done")
    """

    def __init__(self):
        self._data: dict[str, Status] = load_json(PROGRESS_FILE) or {}
        log.info(
            f"Checkpoint loaded: "
            f"{self._count('done')} done, "
            f"{self._count('failed') + self._count('error')} errors"
        )

    # ── Public API ─────────────────────────────────────────────────

    def is_done(self, slug: str) -> bool:
        """Return True if this compound was already completed successfully."""
        return self._data.get(slug) == "done"

    def mark(self, slug: str, status: Status) -> None:
        """Record a status for a compound and persist to disk immediately."""
        self._data[slug] = status
        self._flush()

    def summary(self) -> tuple[int, int]:
        """Return (done_count, error_count)."""
        return (
            self._count("done"),
            self._count("failed") + self._count("error"),
        )

    # ── Internal ───────────────────────────────────────────────────

    def _count(self, status: Status) -> int:
        return sum(1 for v in self._data.values() if v == status)

    def _flush(self) -> None:
        save_json(PROGRESS_FILE, self._data)
