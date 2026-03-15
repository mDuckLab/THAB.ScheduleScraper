import os
import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from webdriver_manager.chrome import ChromeDriverManager
from icalendar import Calendar, Event

# --- CONFIGURATION (Dictionary List) ---
SOURCES = [
    {"url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/SP-DS.html", "filter": []},
    {"url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/SD_2023.html", "filter": []},
    {"url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/Sprachen.html", "filter": ["Engineering English", "Japanisch I"]}
]

def extract_times(cell_text):
    # Regex explanation
    # 8 : 00 or 16:30
    # \d{1,2}  -> Matches 1 or 2 digits (Hour)
    # :        -> Matches a literal colon
    # \d{2}    -> Matches exactly 2 digits (Minutes)
    # \s*-\s* -> Matches a hyphen with optional spaces around it
    # ( )      -> Captures the match into a 'group' we can use later
    #             ( Group 1 )          ( Group 2 )

    # Raw strings (r-strings) treat backslashes as literal text
    time_pattern = r'(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})'
    match = re.search(time_pattern, cell_text)
    
    if match is not None:
        start_time = match.group(1)
        end_time = match.group(2)
        return start_time, end_time
    
    return "00:00", "00:00"

def parse_date_with_year_logic(date_string, detected_years):
    # DD.MM.
    date_match = re.search(r'(\d{2})\.(\d{2})\.', date_string)
    if date_match is None:
        return datetime(2099, 1, 1) # Fallback for invalid dates
    
    day = int(date_match.group(1))
    month = int(date_match.group(2))
    
    # Decide which year to use
    if len(detected_years) > 1:
        # Use first year for December, second year for January
        if month == 12:
            target_year = detected_years[0]
        else:
            target_year = detected_years[1]
    elif len(detected_years) == 1:
        target_year = detected_years[0]
    else:
        target_year = datetime.now().year # Default fallback
        
    return datetime(target_year, month, day)

def save_to_ical(aggregated_data):
    """Creates the .ics file for calendar import."""
    cal = Calendar()
    cal.add('prodid', '-//TH-AB Schedule Scraper//')
    cal.add('version', '2.0')

    for entry in aggregated_data:
        if entry['date_obj'].year == 2099:
            continue
            
        event = Event()
        full_text = entry['content']
        title_parts = full_text.split(' Uhr ')
        clean_title = title_parts[-1][:60] 
        
        event.add('summary', clean_title)
        event.add('description', full_text)
        
        start_h, start_m = map(int, entry['start'].split(':'))
        end_h, end_m = map(int, entry['end'].split(':'))
        
        event.add('dtstart', entry['date_obj'].replace(hour=start_h, minute=start_m))
        event.add('dtend', entry['date_obj'].replace(hour=end_h, minute=end_m))
        
        cal.add_component(event)

    with open('th_schedule.ics', 'wb') as f:
        f.write(cal.to_ical())

def create_chorme_options():
    # Configure Chrome to run invisibly in the background
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    return chrome_options

def create_edge_options():
    edge_options = EdgeOptions()
    edge_options.add_argument("--headless")
    edge_options.add_argument("--window-size=1920,1080")
    return edge_options

def main():
    # user input promt
    print("--- Select browser to scrape ---")
    print("1: Chrome\n2: Edge\n")
    browser_selection = int(input("Select browser:"))

    if (browser_selection == 1):
        options = create_chorme_options()
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    else:
        options = create_edge_options()

        # create driver path for the edge driver
        script_dir = os.path.dirname(os.path.abspath(__file__))
        driver_path = os.path.join(script_dir, "drivers\msedgedriver.exe")

        driver = webdriver.Edge(service=EdgeService(driver_path), options=options)
    
    # Automatic driver management
    final_results = []
    
    try:
        for source in SOURCES:
            print(f"Loading: {source['url']}")
            driver.get(source['url'])
            time.sleep(2) # Give the layout time to stabilize
            
            # finde week headers in html (div class='w2')
            week_divs = driver.find_elements(By.CLASS_NAME, "w2")
            
            for week_header in week_divs:
                header_text = week_header.text
                print(f"{header_text}")
                
                # extract years, they all start with 20 and have two digits
                year_matches = re.findall(r'20\d{2}', header_text)
                detected_years = []
                
                # convert string[] to int[]
                for y_str in year_matches:
                    detected_years.append(int(y_str))
                
                if len(detected_years) == 0:
                    continue # Skip this block if no year info found

                # 2. FIND ASSOCIATED TABLE
                # The table is a 'sibling' of the div w2 in the HTML tree
                try:
                    # XPath: "./following-sibling::table[1]" means 
                    # "From here, look down and pick the first table"
                    target_table = week_header.find_element(By.XPATH, "./following-sibling::table[1]")
                except:
                    continue # No table found for this week header

                # 3. SCAN DAY HEADERS (Horizontal positions)
                day_elements = target_table.find_elements(By.XPATH, ".//td[contains(text(), ', ')]")
                active_days = []
                for day_el in day_elements:
                    day_text = day_el.text.strip()
                    if any(prefix in day_text for prefix in ["Mo,", "Di,", "Mi,", "Do,", "Fr,"]):
                        loc = day_el.location
                        size = day_el.size
                        active_days.append({
                            "name": day_text,
                            "x_start": loc['x'],
                            "x_end": loc['x'] + size['width']
                        })

                if len(active_days) == 0:
                    continue

                # 4. SCAN SUBJECT CELLS
                content_cells = target_table.find_elements(By.TAG_NAME, "td")
                for cell in content_cells:
                    cell_txt = cell.text.replace('\n', ' ').strip()
                    if len(cell_txt) < 10:
                        continue 
                    
                    # FILTER LOGIC
                    should_process = False
                    if len(source['filter']) == 0:
                        should_process = True
                    else:
                        for keyword in source['filter']:
                            # Regex with Word Boundaries (\b) to match "Japanisch I" but not "Japanisch II"
                            if re.search(rf"\b{re.escape(keyword)}(?![IVX])\b", cell_txt, re.I):
                                should_process = True
                                break
                    
                    if should_process:
                        cell_loc = cell.location
                        cell_size = cell.size
                        cell_x_start = cell_loc['x']
                        cell_x_end = cell_x_start + cell_size['width']
                        
                        # OVERLAP LOGIC: Match cell to a day by checking X-coordinates
                        matched_day_name = "Unknown"
                        for d in active_days:
                            overlap = max(0, min(cell_x_end, d['x_end']) - max(cell_x_start, d['x_start']))
                            if overlap > 0:
                                matched_day_name = d['name']
                                break
                        
                        if matched_day_name != "Unknown":
                            start_t, end_t = extract_times(cell_txt)
                            date_obj = parse_date_with_year_logic(matched_day_name, detected_years)
                            
                            final_results.append({
                                "date_obj": date_obj,
                                "start": start_t,
                                "end": end_t,
                                "content": cell_txt
                            })
                            print(f"✅ Found: {date_obj.strftime('%d.%m.%Y')} | {start_t}-{end_t} | {cell_txt[:40]}...")

        # FINAL STEP: Export to File
        if len(final_results) > 0:
            save_to_ical(final_results)
            print(f"\n🚀 Finished! {len(final_results)} events exported to 'th_schedule.ics'")
        else:
            print("\n❌ No matching courses found. Check your filters!")

    finally:
        # Crucial: Always close the invisible browser to free up RAM
        driver.quit()

if __name__ == "__main__":
    main()