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
from selenium.common.exceptions import TimeoutException
import time
from datetime import datetime
import undetected_chromedriver as uc
import re


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
    wait.until(EC.presence_of_element_located((By.NAME, "search_key")))
    print("🟢 Step 1: Page loaded")

    # List all inputs with name=search_key and their visibility (for debugging)
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

        # Find the button and print debug info
        search_button = driver.find_element(By.CSS_SELECTOR, "#search-form button")
        print(f"🔘 Clicking button: {search_button.get_attribute('outerHTML')}")
        search_button.click()

        # Wait a bit for URL to change
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
    wait = WebDriverWait(driver, 30)

    try:
          # ✅ Wait for page to load
        try:
            # First try the main header
            title_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h2.font-weight-600")))
            title = title_element.text.strip()
        except:
            # Fallback: breadcrumb strong text
            title_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.d-none.d-lg-inline strong")))
            title = title_element.text.strip()

        print(f"🟢 Step 2: Product page loaded for '{title}'")
        print(f"title_element HTML: {title_element}")

        # 🟢 Step 3: Grab hidden inputs (they contain JSON with all shows)
        hidden_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type=hidden][id^=Halls]")
        hall_data = []
        for i, inp in enumerate(hidden_inputs):
            val = inp.get_attribute("value")
            print(f"Hidden Input #{i}: value length={len(val)}")
            try:
                hall_data.extend(json.loads(val))
            except:
                # Sometimes the value is not clean JSON, try fixing
                fixed = re.sub(r'([{,])\s*([a-zA-Z0-9_]+):', r'\1"\2":', val)  # add quotes to keys
                try:
                    hall_data.extend(json.loads(fixed))
                except Exception as e:
                    print(f"⚠️ Failed parsing hidden input #{i}: {e}")

        # 🔍 Debug: list all table rows
        # rows = driver.find_elements(By.CSS_SELECTOR, "table.table-stock tbody tr.tr-product")
        # print(f"🟢 Step 4: Found {len(rows)} table rows")
        # for i, row in enumerate(rows):
        #     print(f"Row #{i}: displayed={row.is_displayed()} | stock_uid={row.get_attribute('data-stock-uid')} | hall_uid={row.get_attribute('data-hall-uid')} | date_show={row.get_attribute('data-date-show')}")
        #     print(f"Row {i}: style={row.get_attribute('style')} | stock_uid={row.get_attribute('data-stock-uid')}")
         # 🟢 Step 4: Parse table rows (for prices + availability)

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.table-stock tbody tr.tr-product")))
        rows = driver.find_elements(By.CSS_SELECTOR, "table.table-stock tbody tr.tr-product")
        print(f"🟢 Step 4: Found {len(rows)} table rows")
        results = []

        for idx, row in enumerate(rows):
            stock_uid = row.get_attribute("data-stock-uid")
            hall_uid = row.get_attribute("data-hall-uid")
            date_show = row.get_attribute("data-date-show")

            print(f"Row #{idx}: displayed={row.is_displayed()} | stock_uid={stock_uid} | hall_uid={hall_uid} | date_show={date_show}")

            cols = row.find_elements(By.CSS_SELECTOR, "td")
            if len(cols) < 5:
                print(f"⚠️ Skipping row {idx}, not enough columns")
                continue

            # Prices
            special_price = cols[2].text.replace("₪", "").replace("\u200f", "").strip()
            full_price = cols[3].text.replace("₪", "").replace("\u200f", "").strip()

            # Available seats
            available_text = cols[4].text.strip().split()
            available = available_text[0] if available_text else ""

            # Find hall name from hidden data
            hall_name = ""
            for entry in hall_data:
                if entry.get("stock_uid") == stock_uid or entry.get("d_hall_id") == hall_uid:
                    hall_name = entry.get("hall_area_name") or entry.get("area") or ""
                    break

            # Extract date + time properly
            if date_show and " " in date_show:
                date_part, time_part = date_show.split(" ", 1)
            else:
                date_part, time_part = "", ""

            results.append({
                "title": title,
                "date": date_part,
                "time": time_part,
                "hall": hall_name,
                "special_price": special_price,
                "full_price": full_price,
                "available": available
            })

        print(f"🟢 Step 5: Scraped {len(results)} entries")
        print(results)
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