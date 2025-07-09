import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

def get_short_names():
    service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
    print(service_account_info["private_key"][:300])  # Should begin with "-----BEGIN PRIVATE KEY-----"
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
    client = gspread.authorize(creds)
    

    sheet = client.open("דאטה אפשיט אופיס").worksheet("הפקות")
    data = sheet.get_all_records()

    return [row["שם מקוצר"] for row in data if row["שם מקוצר"]]

def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def search_show(driver, show_name):
    driver.get("https://www.cal-store.co.il")
    wait = WebDriverWait(driver, 10)

    try:
        # 1. Type into search input
        search_input = wait.until(EC.presence_of_element_located((By.NAME, "search_key")))
        search_input.clear()
        search_input.send_keys(show_name)
        search_input.send_keys(Keys.RETURN)

        # 2. Wait for search results to appear
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.link-block")))

        # 3. Get the first search result
        first_result = driver.find_element(By.CSS_SELECTOR, "a.link-block")
        product_url = "https://www.cal-store.co.il" + first_result.get_attribute("href")

        print(f"Found product URL for '{show_name}': {product_url}")
        return product_url

    except Exception as e:
        print(f"No results found for '{show_name}' — {e}")
        return None


def scrape_show_details(driver, product_url):
    if not product_url:
        return []

    driver.get(product_url)
    wait = WebDriverWait(driver, 10)

    try:
        # Get the show title
        title = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.product-title"))).text.strip()

        # Wait for show rows to load
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.table-stock tbody tr.tr-product")))

        # Find all visible rows
        rows = driver.find_elements(By.CSS_SELECTOR, "table.table-stock tbody tr.tr-product")
        results = []

        for row in rows:
            if not row.is_displayed():
                continue  # skip hidden rows

            cols = row.find_elements(By.CSS_SELECTOR, "td")
            if len(cols) < 5:
                continue

            # Clean date + hall text (e.g. "16/08/2025 11:00 היכל התרבות כפר סבא")
            datetime_hall_text = cols[0].text.strip()
            parts = datetime_hall_text.split(" ", 2)  # ['16/08/2025', '11:00', 'היכל התרבות כפר סבא']

            if len(parts) < 3:
                continue

            date = parts[0]
            time = parts[1]
            hall = parts[2]

            # Prices
            special_price = cols[2].text.strip()
            full_price = cols[3].text.strip()

            # Seats available (e.g. "13 מקומות")
            available_text = cols[4].text.strip().split()
            available = available_text[0] if available_text else ""

            results.append({
                "title": title,
                "date": date,
                "time": time,
                "hall": hall,
                "available": available
            })

        return results

    except Exception as e:
        print("❌ Failed to scrape product details:", e)
        return []

def main():
    driver = init_driver()
    short_names = get_short_names()
    for show_name in short_names:
        url = search_show(driver, show_name)
        scrape_show_details(driver, url)
        time.sleep(2)  # polite pause between queries
    driver.quit()

if __name__ == "__main__":
    main()