"""
services/json_client.py
────────────────────────
Responsibilities:
  1. JsonClient   — async HTTP client wrapper with retry logic
  2. BuildIDResolver — fetches and caches the Next.js BUILD_ID from nawy.com
"""

import logging
import re
from typing import Optional

import httpx

from config import BASE_URL, REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAY_S
import asyncio

log = logging.getLogger("nawy.json_client")


class JsonClient:
    """
    Thin wrapper around httpx.AsyncClient.
    Adds retry logic and consistent error handling for all JSON fetches.
    """

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def get(self, url: str) -> Optional[dict]:
        """
        Fetch a URL and return parsed JSON.
        Returns None on 404 or after all retries are exhausted.
        """
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                response = await self._client.get(url, timeout=REQUEST_TIMEOUT)

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 404:
                    log.debug(f"404 (skipping): {url}")
                    return None

                log.warning(
                    f"HTTP {response.status_code} on attempt {attempt}/{RETRY_ATTEMPTS}: {url}"
                )

            except httpx.TimeoutException:
                log.warning(f"Timeout on attempt {attempt}/{RETRY_ATTEMPTS}: {url}")
            except Exception as exc:
                log.warning(f"Error on attempt {attempt}/{RETRY_ATTEMPTS}: {exc}  [{url}]")

            if attempt < RETRY_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_S)

        log.error(f"Gave up after {RETRY_ATTEMPTS} attempts: {url}")
        return None


class BuildIDResolver:
    """
    Reads the Next.js build ID from the nawy.com homepage.

    The build ID changes every time Nawy deploys a new version.
    It appears in the HTML as:
        /_next/static/<BUILD_ID>/_buildManifest.js
    or inside __NEXT_DATA__:
        "buildId": "<BUILD_ID>"

    The resolved ID is cached in memory for the lifetime of the scraper run.
    """

    def __init__(self):
        self._build_id: Optional[str] = None

    async def resolve(self, client: httpx.AsyncClient) -> str:
        """Return the cached BUILD_ID, fetching it first if not yet resolved."""
        if self._build_id:
            return self._build_id

        log.info("Resolving Next.js BUILD_ID from nawy.com …")
        response = await client.get(BASE_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        html = response.text

        # Primary pattern: static asset path
        match = re.search(
            r'/_next/static/([A-Za-z0-9_\-]+)/_buildManifest', html
        )
        # Fallback: __NEXT_DATA__ JSON block
        if not match:
            match = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)

        if not match:
            raise RuntimeError(
                "Could not extract Next.js BUILD_ID from nawy.com — "
                "the page structure may have changed."
            )

        self._build_id = match.group(1)
        log.info(f"BUILD_ID resolved: {self._build_id}")
        return self._build_id
