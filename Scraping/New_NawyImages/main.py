from config import OUTPUT_DIR, LOG_FILE, HTTP_HEADERS, BASE_URL
from models import Compound, Phase, Property
from utils  import safe_name, load_json, save_json, filename_from_url, extract_image_url
from services import JsonClient, BuildIDResolver

from pathlib import Path
import logging, sys, asyncio
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

log = logging.getLogger("nawy")


async def main():
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    log.info("Nawy scraper started.")

    async with httpx.AsyncClient(headers=HTTP_HEADERS, follow_redirects=True) as http:

        # --- TEST BuildIDResolver ---
        resolver = BuildIDResolver()
        build_id = await resolver.resolve(http)
        assert build_id and len(build_id) > 5, "BUILD_ID looks wrong"
        log.info(f"BuildIDResolver    OK  →  {build_id}")

        # --- TEST JsonClient with a real compound URL ---
        from utils import compound_json_url
        client = JsonClient(http)
        url    = compound_json_url(BASE_URL, build_id, "742-stei8ht")
        data   = await client.get(url)
        assert data is not None,               "No data returned"
        assert "pageProps" in data,            "Missing pageProps key"
        compound_raw = data["pageProps"]["compound"]
        assert compound_raw["name"] == "Stei8ht", f"Unexpected name: {compound_raw['name']}"
        log.info(f"JsonClient         OK  →  compound name: {compound_raw['name']}")


        # --- TEST retry on bad URL ---
        bad = await client.get("https://www.nawy.com/_next/data/FAKEID/en/compound/fake.json")
        assert bad is None, "Expected None for bad URL"
        log.info("JsonClient retry   OK  →  bad URL returned None")

    log.info("All services OK.")
    
    
if __name__ == "__main__":
    asyncio.run(main())