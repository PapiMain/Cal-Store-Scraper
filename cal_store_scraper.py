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
    wait = WebDriverWait(driver, 60)

    try:
          # ✅ Wait for page to load
        try:
            # First try the main header
            title_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h2.font-weight-600")))
            title = title_element.text.strip()
        except TimeoutException:
            # Fallback: breadcrumb strong text
            title_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.d-none.d-lg-inline strong")))
            title = title_element.text.strip()

        print(f"🟢 Step 2: Product page loaded for '{title}'")

        # ✅ Wait for hidden input that indicates full JS load
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input.show_hidden_all_halls")))
        print("🟢 Step 3: Hidden halls input loaded")

         # 🔍 Debug: list all hidden inputs
        hidden_inputs = driver.find_elements(By.CSS_SELECTOR, "input.show_hidden_all_halls, input.show_hidden_all_dates")
        for i, inp in enumerate(hidden_inputs):
            print(f"Hidden Input #{i}: value={inp.get_attribute('value')[:200]}...")  # show first 200 chars

        # 🔍 Debug: list all table rows
        rows = driver.find_elements(By.CSS_SELECTOR, "table.table-stock tbody tr.tr-product")
        print(f"🟢 Step 4: Found {len(rows)} table rows")
        for i, row in enumerate(rows):
            print(f"Row #{i}: displayed={row.is_displayed()} | stock_uid={row.get_attribute('data-stock-uid')} | hall_uid={row.get_attribute('data-hall-uid')} | date_show={row.get_attribute('data-date-show')}")
            print(f"Row {i}: style={row.get_attribute('style')} | stock_uid={row.get_attribute('data-stock-uid')}")

        results = []

        for row in rows:
            try:
                # ✅ Use attributes instead of visible text
                stock_uid = row.get_attribute("data-stock-uid")
                hall_uid = row.get_attribute("data-hall-uid")
                date_show = row.get_attribute("data-date-show")

                cols = row.find_elements(By.CSS_SELECTOR, "td")
                if len(cols) < 5:
                    print(f"⚠️ Skipping row {stock_uid}: not enough columns")
                    continue

                # Parse date, time, hall
                datetime_hall_text = cols[0].text.strip()
                parts = datetime_hall_text.split(" ", 2)
                if len(parts) < 3:
                    hall = ""
                else:
                    hall = parts[2]

                date, time = parts[0], parts[1]

                # ✅ Prices
                special_price = cols[2].text.replace("₪", "").replace("\u200f", "").strip()
                full_price = cols[3].text.replace("₪", "").replace("\u200f", "").strip()

                # ✅ Available seats
                available_text = cols[4].text.strip().split()
                available = available_text[0] if available_text else ""

                results.append({
                    "title": title,
                    "date": date_show,
                    "time": time,
                    "hall": hall,
                    "special_price": special_price,
                    "full_price": full_price,
                    "available": available
                })
            except Exception as e_row:
                print(f"⚠️ Failed parsing row {row.get_attribute('data-stock-uid')}: {e_row}")

        print(f"🟢 Step 5: Scraped {len(results)} entries")
        # 🔍 Debug: print first 3 results
        for r in results[:3]:
            print(r)

        return results

    except Exception as e:
        print("❌ Failed to scrape product details:", e)
        # 🔍 Debug: dump page source for investigation
        page_source = driver.page_source
        print(f"🟢 Page source snapshot (first 500 chars): {page_source[:500]}")
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