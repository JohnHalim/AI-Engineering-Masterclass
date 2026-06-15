import asyncio, logging, re
from typing import Optional
import httpx
from config import BASE_URL, REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAY_S

log = logging.getLogger("nawy.json_client")

class JsonClient:
    """Async HTTP client with retry logic for all JSON fetches."""

    def __init__(self, client: httpx.AsyncClient):
        self._client = client
        
    async def get(self, url: str) -> Optional[dict]:
        """Fetch URL and return parsed JSON, or None on failure."""

        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try: 
                response = await self._client.get(url, timeout=REQUEST_TIMEOUT)
                
                if response.status_code == 200:
                    return response.json()
                
                if response.status_code in (404, 500):
                    log.debug(f"{response.status_code} skipping: {url}")
                    return None
                
                log.warning(f"HTTP {response.status_code} attempt {attempt}: {url}")
                
            except httpx.TimeoutException:
                log.warning(f"Timeout attempt {attempt} : {url}")
            except Exception as exc:
                log.warning(f"Error attempt {attempt} : {exc}")
                
            if attempt < RETRY_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_S)
                
            log.error(f"Gave up after {RETRY_ATTEMPTS} attempts: {url}")
            return None
        
        
class BuildIDResolver:
    """
    Reads the Next.js BUILD_ID from nawy.com once and caches it.
    The ID changes every time Nawy deploys — never hardcode it.
    """
    
    def __init__(self):
        self._build_id: Optional[str] = None

    async def resolve(self, client: httpx.AsyncClient) -> str:
        if self._build_id:
            return self._build_id   # return cached value on second call

        log.info("Resolving BUILD_ID from nawy.com ...")
        response = await client.get(BASE_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        html = response.text

        # Primary: look for /_next/static/<BUILD_ID>/_buildManifest.js
        match = re.search(r'/_next/static/([A-Za-z0-9_\-]+)/_buildManifest', html)

        # Fallback: look for "buildId":"<BUILD_ID>" inside __NEXT_DATA__ script
        if not match:
            match = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)

        if not match:
            raise RuntimeError("Could not find BUILD_ID in nawy.com HTML.")

        self._build_id = match.group(1)
        log.info(f"BUILD_ID resolved: {self._build_id}")
        return self._build_id
