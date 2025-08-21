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
from datetime import datetime
import undetected_chromedriver as uc


def get_short_names():
    service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
    client = gspread.authorize(creds)
    

    sheet = client.open("דאטה אפשיט אופיס").worksheet("הפקות")
    data = sheet.get_all_records()

    return [row["שם מקוצר"] for row in data if row["שם מקוצר"]]

def init_driver():
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    # remove --headless
    driver = uc.Chrome(options=options)
    return driver
    
def search_show(driver, show_name):
    driver.get("https://www.cal-store.co.il")
    wait = WebDriverWait(driver, 15)
    print("🟢 Step 1: Page loaded")

    # List all inputs with name=search_key and their visibility
    # inputs = driver.find_elements(By.NAME, "search_key")
    # for i, inp in enumerate(inputs):
    #     print(f"Input #{i}: displayed={inp.is_displayed()} | id={inp.get_attribute('id')} | placeholder={inp.get_attribute('placeholder')}")

    try:
        # Wait explicitly for the visible input
        search_input = None
        for inp in driver.find_elements(By.NAME, "search_key"):
            if inp.is_displayed():
                search_input = inp
                break

        if not search_input:
            raise Exception("No visible search input found")
        
        print(f"✅ Using input: id={search_input.get_attribute('id')} | placeholder={search_input.get_attribute('placeholder')}")

        search_input.clear()
        search_input.send_keys(show_name + Keys.RETURN)
        print(f"✏️ Entered show name: {show_name}")

        # time.sleep(1)

        # Find the button and print debug info
        search_button = driver.find_element(By.CSS_SELECTOR, "#search-form button")
        print(f"🔘 Clicking button: {search_button.get_attribute('outerHTML')}")
        search_button.click()

        # Wait a bit for URL to change
        time.sleep(1)
        print(f"🌐 Current URL after click: {driver.current_url}")

        # Get all product links
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.link-block")))
        all_links = driver.find_elements(By.CSS_SELECTOR, "a.link-block")

        print(f"🔗 Found {len(all_links)} candidate links")

        product_urls = []
        for link in all_links:
            url = link.get_attribute("href")
            aria = link.get_attribute("aria-label") or ""
            parent_text = link.find_element(By.XPATH, "./ancestor::div[contains(@class,'categories__item')]").text

            # Filter by show_name (case-insensitive, space-tolerant)
            if show_name in aria or show_name in parent_text:
                product_urls.append(url)

        if product_urls:
            print(f"✅ Filtered {len(product_urls)} relevant links: {product_urls}")
            return product_urls
        else:
            print(f"⚠️ No relevant links found containing '{show_name}'")
            return []

    except Exception as e:
        print(f"❌ No results found for '{show_name}' — {e}")
        os.makedirs("screenshots", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshots/{show_name}_{timestamp}.png"
        driver.save_screenshot(filename)
        print(f"🖼 Screenshot saved: {filename}")
        return []



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
    all_results = []

    for show_name in short_names:
        urls = search_show(driver, show_name)  # now returns list
        for url in urls:
            results = scrape_show_details(driver, url)
            all_results.extend(results)
            time.sleep(2)

    driver.quit()
    return all_results

if __name__ == "__main__":
    main()