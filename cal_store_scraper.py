import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import json, re, html
import pytz
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
from tabulate import tabulate



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
        search_input.send_keys(show_name)
        print(f"✏️ Entered show name: {show_name}")

        # Wait until the hidden input actually has the value
        wait.until(lambda d: d.find_element(By.NAME, "search_key").get_attribute("value").strip() != "-")

         # Wait for the search results to load
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#search-form button")))

        # Find the button and print debug info
        search_button = driver.find_element(By.CSS_SELECTOR, "#search-form button")
        print(f"🔘 Clicking button: {search_button.get_attribute('outerHTML')}")
        search_button.click()

        # Wait a bit for URL to change
        wait.until(lambda d: "search_key=" in d.current_url)
        print(f"🌐 Current URL after click: {driver.current_url}")
        if "search_key=-" in driver.current_url:
            print("⚠️ URL indicates no results (search_key=-)")
            return []

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
    wait = WebDriverWait(driver, 15)

    try:
        # Check if the specific text exists in the page
        if "מחיר מיוחד ללא שימוש בחוויה" in driver.page_source:
            print("⚠️ Skipping page due to 'מחיר מיוחד ללא שימוש בחוויה'")
            return []
        
        # 🟢 Step 2: Title
        title = ""
        try:
            # Primary: h2 inside the header column (not the table)
            title_el = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div.col-9.col-lg-4 h2.font-weight-600")
            ))
            title = (driver.execute_script("return arguments[0].textContent;", title_el) or "").strip()
        except:
            try:
                # Fallback: strong inside header span
                title_el = driver.find_element(By.CSS_SELECTOR, "span.d-none.d-lg-inline strong")
                title = (driver.execute_script("return arguments[0].textContent;", title_el) or "").strip()
            except:
                title = ""

        print(f"🟢 Step 2: Product page loaded for '{title}'")


        # 🟢 Step 3: Hidden inputs → JSON (all halls & dates)
        halls_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input.show_hidden_all_halls")))
        dates_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input.show_hidden_all_dates")))

        halls_raw = halls_el.get_attribute("value") or "[]"
        dates_raw = dates_el.get_attribute("value") or "[]"

        # Values can be HTML-escaped (&quot; etc). Unescape, then JSON-parse.
        halls_str = html.unescape(halls_raw)
        dates_str = html.unescape(dates_raw)

        try:
            halls_list = json.loads(halls_str)
        except Exception as e:
            print(f"⚠️ halls JSON parse failed ({e}). First 200 chars: {halls_str[:200]}")
            halls_list = []

        try:
            dates_list = json.loads(dates_str)
        except Exception as e:
            print(f"⚠️ dates JSON parse failed ({e}). First 200 chars: {dates_str[:200]}")
            dates_list = []

        print(f"🟢 Hidden JSON: halls={len(halls_list)} entries, dates={len(dates_list)} entries")

        # Build lookups
        hall_by_id = {}
        for h in halls_list:
            hid = h.get("d_hall_id")
            if hid:
                hall_by_id[hid] = h

        stock_to_hall = {}
        stock_to_date = {}
        for d in dates_list:
            sid = d.get("stock_uid")
            if sid:
                stock_to_hall[sid] = d.get("d_hall_id")
                stock_to_date[sid] = d.get("d_end_use_date")

        # 🟢 Step 4: Parse table rows (hidden + visible)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.table-stock tbody tr.tr-product")))
        rows = driver.find_elements(By.CSS_SELECTOR, "table.table-stock tbody tr.tr-product")
        # print(f"🟢 Step 4: Found {len(rows)} table rows")

        results = []

        for idx, row in enumerate(rows):
            stock_uid = row.get_attribute("data-stock-uid") or ""
            hall_uid  = row.get_attribute("data-hall-uid") or ""
            date_show = row.get_attribute("data-date-show") or ""

            print(f"Row #{idx}: displayed={row.is_displayed()} | stock_uid={stock_uid} | hall_uid={hall_uid} | date_show={date_show}")

            cols = row.find_elements(By.CSS_SELECTOR, "td")
            if len(cols) < 5:
                print(f"⚠️ Skipping row {idx}, not enough columns")
                continue

            # Use textContent so we capture values from display:none rows
            def tc(el):
                return (driver.execute_script("return arguments[0].textContent;", el) or "").strip()

            # col[0] looks like: "DD/MM/YYYY HH:MM HALL_NAME"
            col0_text = tc(cols[0])

            # Prices
            special_price = re.sub(r"[^\d]", "", tc(cols[2]))  # keep digits
            full_price    = re.sub(r"[^\d]", "", tc(cols[3]))

            # Available seats (cell includes a button; grab first number)
            avail_text = tc(cols[4])
            m = re.search(r"\d+", avail_text)
            available = m.group(0) if m else ""

            # Hall name: prefer hidden JSON map; fallback to parsed col[0]
            hall_name = ""
            lookup_hall_id = hall_uid or stock_to_hall.get(stock_uid)
            if lookup_hall_id and lookup_hall_id in hall_by_id:
                hall_name = hall_by_id[lookup_hall_id].get("hall_area_name") or hall_by_id[lookup_hall_id].get("area") or ""
            if not hall_name and col0_text:
                # Extract hall name from "date time hall"
                parts = col0_text.split(" ", 2)
                if len(parts) >= 3:
                    hall_name = parts[2].strip()

            # Date/time: prefer attribute; fallback to first TD
            date_part, time_part = "", ""
            src_dt = date_show or stock_to_date.get(stock_uid) or ""
            if src_dt and " " in src_dt:
                date_part, time_part = src_dt.split(" ", 1)
                # trim seconds if present (HH:MM[:SS])
                if len(time_part) >= 5:
                    time_part = time_part[:5]
            elif col0_text:
                # from visible string
                parts = col0_text.split(" ", 2)
                if len(parts) >= 2:
                    date_part = parts[0].strip()
                    time_part = parts[1].strip()

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
        for r in results:
            print(r)
        return results

    except Exception as e:
        print("❌ Failed to scrape product details:", e)
        return []

def update_sheet_with_cal_store_event(scraped_event):

    # ✅ Connect to Google Sheets using service account from env
    service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
    client = gspread.authorize(creds)

    sheet = client.open("דאטה אפשיט אופיס").worksheet("כרטיסים")

    data = sheet.get_all_records()
    headers = sheet.row_values(1)
    sold_col = headers.index("נמכרו") + 1
    updated_col = headers.index("עודכן לאחרונה") + 1

    # Normalize date
    scraped_date = datetime.strptime(scraped_event["date"], "%d/%m/%Y").date()

    israel_tz = pytz.timezone("Asia/Jerusalem")
    now_israel = datetime.now(israel_tz).strftime('%d/%m/%Y %H:%M:%S')

    updated = False

    for i, row in enumerate(data, start=2):  # start=2 because row 1 is headers
        try:
            row_date = row["תאריך"]
            if isinstance(row_date, str):
                try:
                    row_date = datetime.strptime(row_date, "%d/%m/%Y").date()
                except:
                    continue
            elif isinstance(row_date, datetime):
                row_date = row_date.date()

            # Match by title, hall, date, and organization "ויזה כאל"
            if (
                scraped_event["title"].strip() in row["הפקה"].strip() and
                # row["אולם"].strip() == scraped_event["hall"].strip() and
                row_date == scraped_date and
                row["ארגון"].strip() == "ויזה כאל"
            ):
                # Update sold and timestamp
                sold = int(row.get("קיבלו", 0)) - int(scraped_event.get("available", 0))
                sheet.update_cell(i, sold_col, sold)
                sheet.update_cell(i, updated_col, now_israel)
                updated = True
                print(f"✅ Updated row {i}: {scraped_event['title']} - Sold = {sold}")
                break

        except Exception as e:
            print(f"⚠️ Error parsing row {i}: {e}")

    if not updated:
        print(f"❌ No matching row found for {scraped_event['title']} on {scraped_event['date']}")

    return updated  # ✅ Return True if updated, False otherwise

def main():
    driver = init_driver()  # initialize Selenium driver
    short_names = get_short_names()  # get list of shows to search
    all_results = []

    # Lists to track which events were updated and which were not
    updated_data = []
    not_updated = []

    for show_name in short_names:
        urls = search_show(driver, show_name)  # returns list of product URLs
        for url in urls:
            results = scrape_show_details(driver, url)  # scrape event details
            all_results.extend(results)

            # Update sheet for each scraped event
            for event in results:
                updated = update_sheet_with_cal_store_event(event)
                if updated:
                    updated_data.append(event)
                else:
                    not_updated.append(event)

            time.sleep(2)  # be polite with server

    driver.quit()

    # Print tables
    if updated_data:
        print("\n✅ Updated events:")
        print(tabulate(updated_data, headers="keys", tablefmt="grid", stralign="center"))
    else:
        print("\n⚠️ No events were updated.")

    if not_updated:
        print(f"\n⚠️ {len(not_updated)} events were NOT matched in the sheet:")
        print(tabulate(not_updated, headers="keys", tablefmt="grid", stralign="center"))

    return all_results, updated_data, not_updated

if __name__ == "__main__":
    main()