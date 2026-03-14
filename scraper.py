import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from icalendar import Calendar, Event

# --- CONFIGURATION (Dictionary List) ---
SOURCES = [
    {"url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/SP-DS.html", "filter": []},
    {"url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/SD_2023.html", "filter": []},
    {"url": "https://www.th-ab.de/fileadmin/th-ab-redaktion/Stundenplaene/Sprachen.html", "filter": ["Engineering English", "Japanisch I"]}
]

def extract_times(cell_text):
    """
    Finds time patterns like '14:00 - 15:30'.
    Regex: (\d{1,2}:\d{2}) -> Group 1 (Start), (\d{1,2}:\d{2}) -> Group 2 (End)
    """
    time_pattern = r'(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})'
    match = re.search(time_pattern, cell_text)
    
    if match is not None:
        start_time = match.group(1)
        end_time = match.group(2)
        return start_time, end_time
    
    return "00:00", "00:00"

def parse_date_with_year_logic(date_string, detected_years):
    """
    Combines the day/month (e.g. 30.03.) with the detected years from the header.
    Handles weeks that cross into a new year (Dec -> Jan).
    """
    # Regex for DD.MM.
    date_match = re.search(r'(\d{2})\.(\d{2})\.', date_string)
    if date_match is None:
        return datetime(2099, 1, 1) # Fallback for invalid dates
    
    day = int(date_match.group(1))
    month = int(date_match.group(2))
    
    # Decide which year to use
    # If the week header has two years (e.g. 2025 and 2026)
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
            
            # finde week headers in html (div class='w2')
            week_divs = driver.find_elements(By.CLASS_NAME, "w2")
            
            for week_header in week_divs:
                header_text = week_header.text
                print(f"{header_text}")

                # extract years, they all start with 20 and have two digits
                year_matches = re.findall(r'20\d{2}', header_text)
                print(f"{year_matches}")
                detected_years = []
                for y_str in year_matches:
                    detected_years.append(int(y_str))
                    print(f"{detected_years}")


    finally:
        # Crucial: Always close the invisible browser to free up RAM
        driver.quit()

if __name__ == "__main__":
    main()