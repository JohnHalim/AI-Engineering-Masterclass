import time
import logging
import pandas as pd

from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
# from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# import conistants from config file:
from config import (
    BASE_URL, EXCEL_PATH,
    COL_PROJECT_NAME, COL_STARTING_PRICE,
    IMPLICIT_WAIT, EXPLICIT_WAIT
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Build the driver for Edge
def build_driver() -> webdriver.Edge:
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_experimental_option("detach", True)
    service = Service(EdgeChromiumDriverManager().install())
    driver = webdriver.Edge(service=service, options=options)
    driver.implicitly_wait(IMPLICIT_WAIT)
    return driver

# Read excel file on a dataframe, 
# make all field str and perform str functions, 
# handle numeric values and remove Comma sererations
def load_projects(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = df.columns.str.strip()
    df[COL_PROJECT_NAME] = df[COL_PROJECT_NAME].astype(str).str.strip()
    df[COL_STARTING_PRICE] = (
        df[COL_STARTING_PRICE]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    
    log.info("loaded %d projects from %s", len(df), path)
    return df

# 
def wait_clickable(driver, by, selector, timeout=EXPLICIT_WAIT):
    return WebDriverWait(driver=driver, timeout=timeout).until(
        EC.element_to_be_clickable((by, selector))
    )
    

def search_project(driver, project_name: str):
    search_box = wait_clickable(
        driver=driver, 
        by=By.CSS_SELECTOR,
        selector = "input[placeholder*='Search by English or Arabic name']")
    search_box.clear()
    search_box.send_keys(project_name)
    time.sleep(0.8)
    
    
def click_edit_button(driver, project_name: str) -> bool:
    try:
        row = WebDriverWait(driver=driver, timeout= EXPLICIT_WAIT).until(
            EC.presence_of_element_located((
                By.XPATH,
                f"//div[contains(@class,'grid') and .//*[translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') = '{project_name.lower()}']]"
            ))
        )
        driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}))", row)
        time.sleep(0.5)
        edit_btn = row.find_element(By.CSS_SELECTOR, "button[aria-label='Edit']")
        driver.execute_script("arguments[0].scrollIntoView(true);", edit_btn)
        driver.execute_script("arguments[0].click();", edit_btn)
        return True
    except TimeoutException:
        log.warning("Couldn't find row for : %s", project_name)
        return False


def fill_and_save(driver, price: str):
    price_input = wait_clickable(driver=driver, by=By.ID, selector="starting_price")
    price_input.clear()
    price_input.send_keys(price)
    
    save_btn = wait_clickable(
        driver=driver,
        by=By.XPATH,
        selector="//button[@type='submit' and contains(., 'Save changes')]"
    )
    save_btn.click()
    
    WebDriverWait(driver=driver, timeout=EXPLICIT_WAIT).until(
        EC.invisibility_of_element_located((By.ID, "starting_price"))
    )
    

def run():
    df = load_projects(EXCEL_PATH)
    driver = build_driver()
    
    driver.get(BASE_URL)
    log.info("Browser opened. Please log in, then come back here and press ENTER.")
    input("Press ENTER when you are logged in and on the projects page...  ")

    failed = []
    
    for _, row in df.iterrows():
        project_name = row[COL_PROJECT_NAME]
        price = row[COL_STARTING_PRICE]
        
        log.info("Processing: %s → price: %s", project_name, price)
        
        driver.get(BASE_URL)
        time.sleep(0.8)
        
        search_project(driver=driver, project_name=project_name)
        found = click_edit_button(driver=driver, project_name=project_name)
        
        if not found:
            log.error("SKIPPED — not found: %s", project_name)
            failed.append(project_name)
            continue
        
        try:
            fill_and_save(driver=driver, price=price)
            log.info("✓ Saved: %s", project_name)
        except Exception as e:
            log.error("FAILED to save '%s': %s", project_name, e)
            failed.append(project_name)
        
    log.info("─" * 50)
    log.info("Done. %d succeeded, %d failed.", len(df) - len(failed), len(failed))
    if failed:
        log.warning("Failed projects: %s", failed)

if __name__ == "__main__":
    run()
