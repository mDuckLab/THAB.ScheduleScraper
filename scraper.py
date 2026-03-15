import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from icalendar import Calendar, Event

"""
PROJECT: TH-AB Schedule Scraper
GOAL: Automated extraction of TH-AB schedules and conversion into iCal format (.ics).

THE PROBLEM (HTML Index Shift):
In the HTML structure, a table cell index (e.g., Index 1) does not correspond to a fixed weekday. Due to 'rowspan' attributes (lectures spanning multiple time slots), cells are physically absent in subsequent rows, causing data to "slide" to the left in the HTML source.

EXAMPLE:
- Row 1: [Time] [Mon-Lecture (Start)] [Tue-Lecture]
          Index 0    Index 1              Index 2
- Row 2: [Time] [Tue-Lecture]
          Index 0    Index 1  <-- ERROR: Tuesday now occupies Index 1.

THE SOLUTION (Spatial Mapping):
Assignment is performed via physical X-coordinates (pixel positions). Since weekdays occupy fixed "lanes" on the screen, the X-position of each lecture is compared against the previously measured pixel ranges of the day headers.

STRUCTURE & ALGORITHM:
A fixed vertical sequence is utilized: [w1: Course] -> [w2: Date Anchor] -> [table: Data].
The required year is dynamically extracted from the 'w2' anchor. The associated table is identified as the immediate following sibling. This pairing ensures correct temporal assignment even if multiple weeks are displayed on a single page.
"""

# SOURCES configuration with URLs and keywords
"""
SOURCES = [
    {
        "url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/BW_2024.html", 
        "filter": ["Wirtschaftsprivatrecht II - Arbeitsrecht"]

    },
    {
        "url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/FW-RWPMs-Fakultaet_WR.html", 
        "filter": ["Strafrecht", "Praxis der Bankbetriebslehre", "Medienrecht"]
    },
    {
        "url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/SP-WR_Rechtsfragen_Personalmanagement.html", 
        "filter": ["Fall-/Projektstudien zu Personalmanagement"]
    }
]
"""

SOURCES = [
    {"url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/SP-MST.html", "filter": []},
    {"url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/SP-MSE.html", "filter": []},
    {"url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/Sprachen.html", "filter": ["Engineering English"]}
]

# TARGET_GROUP: Set this to "Gr. 1" or "Gr. 2" to filter specific groups, or None for all.
TARGET_GROUP = "None" 

def extract_times(cell_text):
    # Regex explanation
    # 8 : 00 or 16:30
    # \d{1,2}  -> Matches 1 or 2 digits (Hour)
    # :         -> Matches a literal colon
    # \d{2}    -> Matches exactly 2 digits (Minutes)
    # \s*-\s* -> Matches a hyphen with optional spaces around it
    # ( )      -> Captures the match into a 'group' we can use later
    #              ( Group 1 )          ( Group 2 )

    # Raw strings (r-strings) treat backslashes as literal text
    time_pattern = r'(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})'
    match = re.search(time_pattern, cell_text)
    
    if match is not None:
        start_time = match.group(1)
        end_time = match.group(2)
        return start_time, end_time
    
    return None, None # Changed to None to make filtering easier

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

def clean_event_title(full_text):
    """Removes the time prefix and type (V, PR, Ü) to keep only subject, prof, and room."""
    # Beispiel: "15:45 - 17:15 Uhr V Medienrecht..." -> "Medienrecht..."
    # 1. Alles vor und inklusive " Uhr " entfernen
    parts = full_text.split(' Uhr ')
    if len(parts) > 1:
        text_after_uhr = parts[-1].strip()
        # 2. Führende Kürzel wie V, PR, Ü, S plus Leerzeichen entfernen
        # (Sucht nach 1-2 Großbuchstaben am Anfang gefolgt von Leerzeichen)
        cleaned = re.sub(r'^[A-Z]{1,2}\s+', '', text_after_uhr)
        return cleaned
    return full_text

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
        
        # PROCESSING: Clean the title for the calendar entry
        clean_title = clean_event_title(full_text)
        
        event.add('summary', clean_title)
        event.add('description', full_text)
        
        start_h, start_m = map(int, entry['start'].split(':'))
        end_h, end_m = map(int, entry['end'].split(':'))
        
        event.add('dtstart', entry['date_obj'].replace(hour=start_h, minute=start_m))
        event.add('dtend', entry['date_obj'].replace(hour=end_h, minute=end_m))
        
        cal.add_component(event)

    with open('th_schedule.ics', 'wb') as f:
        f.write(cal.to_ical())

def main():
    # browser setup
    # Configure Chrome to run invisibly in the background
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Automatic driver management
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    final_results = []
    
    try:
        for source in SOURCES:
            print(f"Loading: {source['url']}")
            driver.get(source['url'])
            time.sleep(2) # Give the layout time to stabilize
            
            # 1) finde week headers in html (div class='w2') 
            # References to these elements are saved in a list.
            # These headers are required to extract the specific year (e.g., '2026'), 
            # as the individual day cells within the table often lack year information.
            week_divs = driver.find_elements(By.CLASS_NAME, "w2")
            
            for week_header in week_divs:
                # get the text from object: e.g. Woche: 16. - 22.03.2026
                header_text = week_header.text
                
                # extract years, they all start with 20 and have two digits
                year_matches = re.findall(r'20\d{2}', header_text)
                detected_years = []
                
                # convert string[] to int[]
                for y_str in year_matches:
                    detected_years.append(int(y_str))
                
                if len(detected_years) == 0:
                    continue # Skip this block if no year found

                # 2) finde associated tabel to header
                try:
                    # XPath: "./following-sibling::table[1]" means 
                    # "From here, look down and pick t
                    # # WARNING: If a 'w2' is missing its table, this will grab the NEXT week's 
                    # table, causing duplicate entries with wrong dates. We accept this risk 
                    # for simplicity unless the TH-AB site structure changes significantly.
                    target_table = week_header.find_element(By.XPATH, "./following-sibling::table[1]")
                except:
                    continue # No table found for this week header


                # mapping logic (day to lecture)

                # A broad XPath filter is applied to identify potential candidates 
                # containing a comma. This significantly reduces the number of 
                # elements transferred from the browser to Python, optimizing 
                # performance before the specific weekday verification occurs.
                day_elements = target_table.find_elements(By.XPATH, ".//td[contains(text(), ', ')]")
                active_days = []
                for day_el in day_elements:
                    day_text = day_el.text.strip() # Text is cleaned for accurate prefix matching
                    
                    # Weekdays are filtered and their physical screen boundaries are stored.
                    if any(prefix in day_text for prefix in ["Mo,", "Di,", "Mi,", "Do,", "Fr,"]):
                        loc, size = day_el.location, day_el.size
                        active_days.append({
                            "name": day_text,
                            "x_start": loc['x'],
                            "x_end": loc['x'] + size['width']
                        })

                if len(active_days) == 0:
                    continue

                # 4) scan subject cells (table)
                # td = Table Data
                content_cells = target_table.find_elements(By.TAG_NAME, "td")
                for cell in content_cells:
                    cell_txt = cell.text.replace('\n', ' ').strip()
                    # Short data fragments are discarded to optimize processing of relevant information.
                    if len(cell_txt) < 10:
                        continue
                    
                    # filter logic
                    # The 'should_process' flag acts as a gatekeeper: it is only set to True 
                    # if the cell matches the defined keywords or if no filters are applied.
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
                        # Skip entries that don't contain a valid time
                        start_t, end_t = extract_times(cell_txt)
                        if start_t is None:
                            continue
                        
                        # Time Range Filter (7:00 - 22:00)
                        start_hour = int(start_t.split(':')[0])
                        if not (7 <= start_hour <= 22):
                            continue

                        # GROUP FILTER: Logic to exclude other groups if TARGET_GROUP is specified.
                        if TARGET_GROUP:
                            other_group = "Gr. 2" if TARGET_GROUP == "Gr. 1" else "Gr. 1"
                            if other_group in cell_txt and TARGET_GROUP not in cell_txt:
                                continue

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
                            date_obj = parse_date_with_year_logic(matched_day_name, detected_years)
                            
                            final_results.append({
                                "date_obj": date_obj,
                                "start": start_t,
                                "end": end_t,
                                "content": cell_txt
                            })

        # FINAL STEP: Organized Terminal Output & Export
        if len(final_results) > 0:
            # Enhanced Sorting: Date, then Hour (int), then Minute (int)
            final_results.sort(key=lambda x: (
                x['date_obj'], 
                int(x['start'].split(':')[0]), 
                int(x['start'].split(':')[1])
            ))
            
            current_week = None
            for entry in final_results:
                week_num = entry['date_obj'].isocalendar()[1]
                
                if week_num != current_week:
                    current_week = week_num
                    print(f"\n--- CALENDAR WEEK {current_week} ({entry['date_obj'].year}) ---")
                
                day_label = entry['date_obj'].strftime('%a, %d.%m.')
                # Clean version for terminal output
                display_content = clean_event_title(entry['content'])
                print(f"  [{day_label}] {entry['start']:>5}-{entry['end']:>5} | {display_content[:75]}...")

            save_to_ical(final_results)
            print(f"\n🚀 Finished! {len(final_results)} events exported to 'th_schedule.ics'")
        else:
            print("\n❌ No matching courses found. Check your filters!")

    finally:
        # Crucial: Always close the invisible browser to free up RAM
        driver.quit()

if __name__ == "__main__":
    main()