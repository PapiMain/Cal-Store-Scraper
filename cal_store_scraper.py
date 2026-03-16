from datetime import datetime
import os
import json, re, html
import pytz
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from datetime import datetime
import undetected_chromedriver as uc
from tabulate import tabulate
from py_appsheet import AppSheetClient


def get_appsheet_client():
    return AppSheetClient(
        app_id=os.environ.get("APPSHEET_APP_ID"),
        api_key=os.environ.get("APPSHEET_APP_KEY"),
    )

def get_short_names():
    """Fetches show names from AppSheet instead of GSpread."""
    client = get_appsheet_client()
    try:
        # Fetching from 'הפקות' table
        rows = client.find_items("הפקות", "")
        return [row["שם מקוצר"] for row in rows if row.get("שם מקוצר")]
    except Exception as e:
        print(f"❌ Error fetching short names: {e}")
        return []

def send_appsheet_batch(table_name, updates):
    """Sends a batch 'Edit' action directly to the AppSheet API."""
    app_id = os.environ.get("APPSHEET_APP_ID")
    api_key = os.environ.get("APPSHEET_APP_KEY")
    
    url = f"https://api.appsheet.com/api/v1/apps/{app_id}/tables/{table_name}/Action"
    
    headers = {
        "ApplicationToken": api_key,
        "Content-Type": "application/json"
    }
    
    body = {
        "Action": "Edit",
        "Properties": {
            "Locale": "en-US",
            "Timezone": "Israel Standard Time"
        },
        "Rows": updates
    }
    
    try:
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        print(f"✅ AppSheet API Response: {response.status_code} - Success")
        return True
    except Exception as e:
        print(f"❌ API Post Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Context: {e.response.text}")
        return False
    
def init_driver():
    
    chrome_version = os.environ.get("CHROME_VER")
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # temp no headless
    # options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")

    # NEW: point explicitly to the upgraded Chrome
    options.binary_location = "/usr/bin/google-chrome-stable"
    
    if chrome_version:
        print(f"🔧 Launching ChromeDriver for Chrome v{chrome_version}")
        driver = uc.Chrome(version_main=int(chrome_version), options=options)
    else:
        print("⚠️ CHROME_VER not found, using default ChromeDriver")
        driver = uc.Chrome(options=options)

    return driver
    
def search_show(driver, show_name):
    driver.get("https://www.cal-store.co.il")
    
    # temp debugging
    # time.sleep(5)
    # print(driver.page_source[:1000])  # first 1000 chars

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
        
        # print(f"✅ Using input: id={search_input.get_attribute('id')} | placeholder={search_input.get_attribute('placeholder')}")

        search_input.clear()
        search_input.send_keys(show_name)
        print(f"✏️ Entered show name: {show_name}")

        # Wait until the hidden input actually has the value
        wait.until(lambda d: d.find_element(By.NAME, "search_key").get_attribute("value").strip() != "-")

         # Wait for the search results to load
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#search-form button")))

        # Find the button and print debug info
        search_button = driver.find_element(By.CSS_SELECTOR, "#search-form button")
        # print(f"🔘 Clicking button: {search_button.get_attribute('outerHTML')}")
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

        # print(f"🟢 Hidden JSON: halls={len(halls_list)} entries, dates={len(dates_list)} entries")

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

            # print(f"Row #{idx}: displayed={row.is_displayed()} | stock_uid={stock_uid} | hall_uid={hall_uid} | date_show={date_show}")

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

        print(f"🟢 number of events: Scraped {len(results)} entries")
        for r in results:
            print(r)
        return results

    except Exception as e:
        print("❌ Failed to scrape product details:", e)
        return []

def update_appsheet_events(scraped_events):
    """Updates AppSheet table 'הופעות עתידיות' using batch Edit action."""
    client = get_appsheet_client()
    
    # 1. Get existing data from AppSheet to find matching rows
    try:
        print("⏳ Fetching current AppSheet records for matching...")
        app_rows = client.find_items("הופעות עתידיות", "")
    except Exception as e:
        print(f"❌ AppSheet fetch error: {e}")
        return [], scraped_events

    israel_tz = pytz.timezone("Asia/Jerusalem")
    now_israel = datetime.now(israel_tz).strftime('%d/%m/%Y %H:%M')
    
    batch_updates = []
    matched_events = []
    unmatched_events = []

    for event in scraped_events:
        try:
            scraped_date_str = datetime.strptime(event["date"], "%d/%m/%Y").date()
            matched = False

            for row in app_rows:
                # AppSheet usually returns dates as strings or ISO. 
                # Adjust format if your AppSheet date format is different.
                row_date_str = str(row.get("תאריך", ""))
                if not row_date_str:
                    continue

                try:
                    row_date_obj = datetime.strptime(row_date_str, "%m/%d/%Y").date()
                except ValueError:
                    # Fallback in case AppSheet format changes
                    try:
                        row_date_obj = datetime.strptime(row_date_str, "%d/%m/%Y").date()
                    except:
                        continue
                event_name = event["title"].strip()
                row_name = row.get("הפקה", "").strip()

                # for debugging:
                # print(f"Matching Event '{event_name}' on {scraped_date_str} against Row '{row_name}' on {row_date}'")

                if "סימבה" in event_name and "סוואנה" not in event_name and "אפריקה" not in event_name:
                    event_name = "סימבה מלך"

                if "עכבר העיר" in event_name:
                    event_name = "עכבר העיר"

                title_match = (event_name in row_name or row_name in event_name)
                
                exclude_words = ["סוואנה", "אפריקה", "הפקת הענק"]

                if "סימבה" in event_name or "פיטר פן" in event_name:
                    if any(word in event_name for word in exclude_words):
                        title_match = False

                
                # Matching Logic
                if title_match and row_date_obj == scraped_date_str and row.get("ארגון") == "ויזה כאל":
                    try:
                        # Calculation: Received - Available
                        received = int(row.get("קיבלו", 0))
                        available = int(event.get("available", 0))
                        sold = received - available

                        # Fix for negative numbers
                        if sold < 0:
                            print(f"⚠️ Warning: Negative sold tickets for {row_name}. Setting to 0.")
                            sold = 0
                    except:
                        sold = 0

                    # AppSheet Batch Object
                    batch_updates.append({
                        "ID": row["ID"], # Using the Key column
                        "נמכרו": sold,
                        "עודכן לאחרונה": now_israel
                    })
                    
                    matched_events.append(event)
                    matched = True
                    break
            
            if not matched:
                unmatched_events.append(event)

        except Exception as e:
            print(f"⚠️ Error processing {event.get('title')}: {e}")
            unmatched_events.append(event)

    # 2. Perform the API Update
    if batch_updates:
        print(f"📤 Sending {len(batch_updates)} rows to AppSheet API...")
        send_appsheet_batch("הופעות עתידיות", batch_updates)
    else:
        print("ℹ️ No updates to send.")
    
    return matched_events, unmatched_events

def main():
    driver = init_driver()  # initialize Selenium driver
    short_names = get_short_names()  # get list of shows to search
    all_results = []

    for show_name in short_names:
        urls = search_show(driver, show_name)  # returns list of product URLs
        for url in urls:
            results = scrape_show_details(driver, url)  # scrape event details
            all_results.extend(results)
            time.sleep(2)  # be polite with server

    driver.quit()
    
    matched, unmatched = update_appsheet_events(all_results)

    if matched:
        print("\n✅ Updated events:")
        print(tabulate(matched, headers="keys", tablefmt="grid"))
    else:
        print("\n⚠️ No events were updated.")

    if unmatched:
        print(f"\n⚠️ {len(unmatched)} events were NOT matched:")
        print(tabulate(unmatched, headers="keys", tablefmt="grid"))

if __name__ == "__main__":
    main()
