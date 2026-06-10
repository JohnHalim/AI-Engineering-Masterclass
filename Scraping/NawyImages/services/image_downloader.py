"""
services/image_downloader.py
─────────────────────────────
Responsibilities:
  ImageDownloader — downloads images concurrently to disk.
    • download_one()   — download a single image URL to a Path
    • download_batch() — download a list of URLs into a folder
"""

import asyncio
import logging
from pathlib import Path

import aiofiles
import httpx

from config import REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAY_S, DOWNLOAD_CONCURRENCY
from utils.url_utils import filename_from_url

log = logging.getLogger("nawy.downloader")


class ImageDownloader:
    """
    Downloads images asynchronously.

    Uses a semaphore to cap the number of simultaneous downloads
    at DOWNLOAD_CONCURRENCY (configured in config.py).
    Skips files that already exist on disk (safe to re-run / resume).
    """

    def __init__(self, client: httpx.AsyncClient):
        self._client    = client
        self._semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

    async def download_one(self, url: str, dest: Path) -> bool:
        """
        Download a single image to dest.
        Returns True on success, False on failure.
        Skips if dest already exists.
        """
        if dest.exists():
            return True  # already downloaded in a previous run

        async with self._semaphore:
            for attempt in range(1, RETRY_ATTEMPTS + 1):
                try:
                    response = await self._client.get(url, timeout=REQUEST_TIMEOUT)

                    if response.status_code == 200:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        async with aiofiles.open(dest, "wb") as f:
                            await f.write(response.content)
                        log.debug(f"  ✓  {dest.name}")
                        return True

                    if response.status_code == 404:
                        log.debug(f"  404 (skipping): {url}")
                        return False

                    log.warning(
                        f"  HTTP {response.status_code} on attempt "
                        f"{attempt}/{RETRY_ATTEMPTS}: {url}"
                    )

                except httpx.TimeoutException:
                    log.warning(f"  Timeout attempt {attempt}/{RETRY_ATTEMPTS}: {url}")
                except Exception as exc:
                    log.warning(f"  Error attempt {attempt}/{RETRY_ATTEMPTS}: {exc}")

                if attempt < RETRY_ATTEMPTS:
                    await asyncio.sleep(RETRY_DELAY_S)

        log.error(f"  Failed after {RETRY_ATTEMPTS} attempts: {url}")
        return False

    async def download_batch(
        self,
        urls: list[str],
        folder: Path,
        label: str = "",
    ) -> int:
        """
        Download a list of image URLs into folder.
        Each file is named using filename_from_url().
        Returns the count of successfully saved images.
        """
        if not urls:
            return 0

        folder.mkdir(parents=True, exist_ok=True)

        tasks = [
            self.download_one(url, folder / filename_from_url(url, i))
            for i, url in enumerate(urls)
        ]

        results = await asyncio.gather(*tasks)
        count   = sum(1 for ok in results if ok)

        if count:
            log.info(f"  ✓  [{label}]  {count}/{len(urls)} images  →  {folder}")
        elif urls:
            log.warning(f"  ✗  [{label}]  0/{len(urls)} images saved  →  {folder}")

        return count
