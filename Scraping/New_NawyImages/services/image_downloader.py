import asyncio, logging
from pathlib import Path
import aiofiles
import httpx
from config import REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAY_S, DOWNLOAD_CONCURRENCY
from utils.url_utils import filename_from_url

log = logging.getLogger("nawy.downloader")


class ImageDownloader:
    """
    Downloads images asynchronously with a concurrency limit.
    Skips files that already exist on disk.
    """

    def __init__(self, client: httpx.AsyncClient):
        self._client    = client
        # semaphore caps how many downloads run at the same time
        self._semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

    async def download_one(self, url: str, dest: Path) -> bool:
        """Download a single image. Returns True on success."""
        if dest.exists():
            return True  # already downloaded, skip

        async with self._semaphore:
            for attempt in range(1, RETRY_ATTEMPTS + 1):
                try:
                    response = await self._client.get(url, timeout=REQUEST_TIMEOUT)

                    if response.status_code == 200:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        async with aiofiles.open(dest, "wb") as f:
                            await f.write(response.content)
                        log.debug(f"✓ {dest.name}")
                        return True

                    if response.status_code == 404:
                        log.debug(f"404 skipping: {url}")
                        return False

                    log.warning(f"HTTP {response.status_code} attempt {attempt}: {url}")

                except httpx.TimeoutException:
                    log.warning(f"Timeout attempt {attempt}: {url}")
                except Exception as exc:
                    log.warning(f"Error attempt {attempt}: {exc}")

                if attempt < RETRY_ATTEMPTS:
                    await asyncio.sleep(RETRY_DELAY_S)

        log.error(f"Failed after {RETRY_ATTEMPTS} attempts: {url}")
        return False

    async def download_batch(self, urls: list[str], folder: Path, label: str = "") -> int:
        """
        Download a list of image URLs into folder.
        Runs all downloads concurrently (limited by semaphore).
        Returns count of successfully saved images.
        """
        if not urls:
            return 0

        folder.mkdir(parents=True, exist_ok=True)

        # build all tasks first, then run them together
        tasks = [
            self.download_one(url, folder / filename_from_url(url, i))
            for i, url in enumerate(urls)
        ]

        results = await asyncio.gather(*tasks)
        count   = sum(1 for ok in results if ok)
        log.info(f"  ✓  [{label}]  {count}/{len(urls)} images  →  {folder}")
        return count