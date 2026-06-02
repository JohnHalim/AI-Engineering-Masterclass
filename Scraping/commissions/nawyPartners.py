from playwright.sync_api import sync_playwright
import requests
import pandas as pd


API_URL = "https://api-fauna-prod.nawy.com/compounds/filter"


def get_token():

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False
        )

        page = browser.new_page()

        page.goto("https://partners.nawy.com")

        input("Login manually and open commissions page, then press Enter...")

        page.wait_for_load_state("networkidle")

        storage = page.evaluate("() => Object.assign({}, localStorage)")

        token = storage["accessToken"]

        browser.close()

        return token


token = get_token()


headers = {

    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
}


all_rows = []


# first request to know pages

response = requests.get(
    API_URL,
    headers=headers,
    params={"page":1}
)

first_data = response.json()

total_pages = first_data["pages"]

print(
    f"Total Pages: {total_pages}"
)


for page_num in range(1, total_pages + 1):

    print(f"Scraping page {page_num}/{total_pages}")

    response = requests.get(
        API_URL,
        headers=headers,
        params={"page": page_num}
    )

    data = response.json()

    compounds = data["data"]

    for item in compounds:

        commission = item.get("commission") or {}

        developer = item.get("developer") or {}

        row = {
            "developer":
                developer.get("name"),
            "compound":
                item.get("name"),
            "normal_commission":
                commission.get(
                    "normal"),
            "express_commission":
                commission.get(
                    "express")}

        all_rows.append(row)


df = pd.DataFrame(all_rows)

df.to_csv(
    "commissions.csv",
    index=False,
    encoding="utf-8-sig")

print(f"Done. Saved {len(df)} rows.")