#!/usr/bin/env python3

import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from fuzzywuzzy import fuzz
import smtplib
from email.utils import formataddr
import os
import csv
import json
import ast
import re

today = datetime.date.today().strftime("%Y%m%d")

currently_showing_list = []

# urgoo.mn now redirects to new.urgoo.mn (Next.js). Movie links must be built on
# new.urgoo.mn: urgoo.mn/movies/... redirects to the old www server and 404s.
url = 'https://new.urgoo.mn/'
# Homepage sections: "now-showing" (Яг одоо дэлгэцнээ) and "coming-soon" (Тун удахгүй)
SECTION_ID = "now-showing"
file_name = f'/Users/user/Documents/Python/2025/Day_12_Urgoo_Cinema/output/currently_showing_list_{today}.csv'

chrome_options = Options()
chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--headless=new")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)

# Ratings seen on the site: G, PG, PG13, R, R16 ... (also accept R18, NC-17, 16+)
RATING_PATTERN = re.compile(r'^(G|PG|PG-?13|R(-?\d{2})?|NC-?17|\d{1,2}\+)$', re.IGNORECASE)


def close_floating_ad(driver, wait_seconds=3):
    """Dismiss the floating ad dialog if one shows up; never block if it doesn't."""
    try:
        presentation = WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='presentation']"))
        )
        presentation.find_element(By.TAG_NAME, "svg").click()
        print("Clicked X on a floating ad!")
    except (TimeoutException, NoSuchElementException):
        pass  # no ad, or no close icon inside it — fine either way


def movie_extract():
    driver = webdriver.Chrome(options=chrome_options)
    driver.get(url)
    movie_list = []
    try:
        close_floating_ad(driver)

        section = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, SECTION_ID))
        )
        cards = section.find_elements(By.CSS_SELECTOR, "a[href*='/movies/']")
        for card in cards:
            movie_link = card.get_attribute("href")
            # Each card has an aria-hidden blurred placeholder <img> first; the real
            # poster is the first Next.js fill image and carries the title as alt.
            posters = card.find_elements(By.CSS_SELECTOR, "img[data-nimg='fill']")
            if not posters:
                print(f"⚠️ No poster image found for {movie_link}, skipping")
                continue
            img_link = posters[0].get_attribute("src")
            movie_name = (posters[0].get_attribute("alt") or "").strip()
            movie_list.append({
                "movie_name": movie_name,
                "movie_link": movie_link,
                "img_link": img_link,
            })

    except (NoSuchElementException, TimeoutException) as error:
        print(f"❌ Could not read the '{SECTION_ID}' section: {error}")
    driver.quit()
    return movie_list


def movie_info(links):
    driver = webdriver.Chrome(options=chrome_options)
    for movie in links:
        movie_link = movie.get("movie_link")
        try:
            driver.get(movie_link)
            close_floating_ad(driver)

            try:
                # The info box is the most stable anchor on the new detail page.
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-slot='info-row']"))
                )

                # Title: prefer the page <h1>, fall back to the card's alt text
                headings = driver.find_elements(By.TAG_NAME, "h1")
                movie_name = next((h.text.strip() for h in headings if h.text.strip()), None) \
                    or movie.get("movie_name")

                # Description: the <p> right after the info rows, inside the info box
                info_box = driver.find_element(By.CSS_SELECTOR, r"div.bg-foreground\/5.rounded-lg")
                paragraphs = info_box.find_elements(By.TAG_NAME, "p")
                movie_description = paragraphs[0].text.strip() if paragraphs else "N/A"

                # Branches showing the movie on the selected (today's) date
                branches = {"Urgoo": []}
                for branch in driver.find_elements(By.CSS_SELECTOR, "div.divide-y > div"):
                    names = branch.find_elements(By.CSS_SELECTOR, "p.text-foreground")
                    if names and names[0].text.strip():
                        branches["Urgoo"].append(names[0].text.strip())
                # Fallback: the branch dropdown lists every branch screening the film
                if not branches["Urgoo"]:
                    for option in driver.find_elements(By.CSS_SELECTOR, "select option"):
                        if option.get_attribute("value") != "all" and option.text.strip():
                            branches["Urgoo"].append(option.text.strip())
                theater_names = [branches]

                movie_dict = {
                    "movie_name": movie_name,
                    "movie_description": movie_description,
                    "movie_genre": None,
                    "movie_duration": None,
                    "movie_rating": None,
                    "movie_start_date": None,
                    "screens": theater_names,
                    "theater": "Urgoo",
                    "movie_link": movie_link,
                    "img_link": movie.get("img_link"),
                }

                # Info rows: Хугацаа / Өргөөгийн дэлгэцнээ / IMDb үнэлгээ / <rating> / Найруулагч / Төрөл
                for row in driver.find_elements(By.CSS_SELECTOR, "[data-slot='info-row']"):
                    try:
                        key = row.find_element(By.CSS_SELECTOR, "[data-slot='info-row-title']").text.strip()
                        value = row.find_element(By.CSS_SELECTOR, "[data-slot='info-row-description']").text.strip()
                        if key == "Төрөл":
                            movie_dict["movie_genre"] = value
                        elif key == "Хугацаа":
                            movie_dict["movie_duration"] = value
                        elif RATING_PATTERN.match(key):
                            movie_dict["movie_rating"] = key
                        elif key == "Өргөөгийн дэлгэцнээ":
                            movie_dict["movie_start_date"] = value
                    except NoSuchElementException as e:
                        print(f"⚠️ Skipped a malformed info row in {movie_link}: {e}")

                currently_showing_list.append(movie_dict)

            except TimeoutException:
                print(f"❌ Info box never appeared on {movie_link}; skipping.")
                continue
            except NoSuchElementException as error:
                print(f"❌ Missing expected element in {movie_link}: {error}")
            except Exception as e:
                print(f"⚠️ General block error in {movie_link}: {e}")

            print(f"Finished scraping {movie_link}")

        except Exception as e:
            print(f"❌ Error processing {movie_link}: {e}")

    driver.quit()

    # Check and combine movie names in csv.
    if os.path.exists(file_name):
        # 1. Read existing rows into memory first
        with open(file_name, mode="r", newline='', encoding="utf-8") as movie_file:
            reader = csv.DictReader(movie_file)
            fieldnames = reader.fieldnames
            existing_rows = list(reader)

        # 2. Modify in memory
        def safe_parse_list(value):
            if not value:
                return []
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                try:
                    return ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    return [value]

        for row in existing_rows:
            movie = row["movie_name"]
            screens = safe_parse_list(row["screens"]) if row["screens"] else []
            theaters = safe_parse_list(row["theater"]) if row["theater"] else []
            movie_url = safe_parse_list(row["movie_link"]) if row["movie_link"] else []

            for film in list(currently_showing_list):
                similarity = fuzz.token_set_ratio(movie.lower(), film["movie_name"].lower())
                if similarity > 90:
                    screens.extend(film["screens"])
                    theaters.append(film["theater"])  # or .extend() if film["theater"] is itself a list
                    movie_url.append(film["movie_link"])
                    currently_showing_list.remove(film)

            row["screens"] = json.dumps(screens, ensure_ascii=False)
            row["theater"] = json.dumps(theaters, ensure_ascii=False)
            row["movie_link"] = json.dumps(movie_url, ensure_ascii=False)

        # 3. Write back
        with open(file_name, mode="w", newline='', encoding="utf-8") as movie_file:
            writer = csv.DictWriter(movie_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_rows)

    # Save to CSV
    if currently_showing_list:
        mode = "a" if os.path.exists(file_name) else "w"
        write_header = mode == "w"
        fieldnames = currently_showing_list[0].keys()

        with open(file_name, mode=mode, newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(currently_showing_list)

        print(f"✅ Successfully finished saving to {file_name}. Total {len(currently_showing_list)} movies are found")

    return currently_showing_list


def movie_tracker(total_list):
    with open("/Users/user/Documents/Python/2025/Day_12_Urgoo_Cinema/files/my_movies.txt", mode="r", encoding="utf-8") as movie_file:
        my_movies = movie_file.readlines()
    matched_movie_text = []
    matched_movies = set()
    number = 1
    for movie in my_movies:
        for film in total_list:
            similarity = fuzz.token_set_ratio(movie.lower(), film["movie_name"].lower())
            if similarity > 80:
                text = (
                    f"{number}. {film['movie_name'].upper()} ({film['movie_rating']}, {film['movie_duration']}) "
                    f"in Urgoo! "
                    f"Starts {film['movie_start_date']}. Available in {film['screens']}")
                matched_movie_text.append(text)
                matched_movies.add(movie)
                number += 1

    if matched_movies:
        # If there are matched movies, delete them from my_movies.txt by overwriting.
        with open("files/my_movies.txt", "w", encoding="utf-8") as file:
            for movie in my_movies:
                if movie not in list(matched_movies):
                    file.write(movie)

        # Combine the texts in one text with line breaks
        combined_text = "\n\n".join(matched_movie_text)

        # Send the combined text to email
        with smtplib.SMTP("smtp.gmail.com", port=587) as connection:
            my_email = os.getenv("MY_EMAIL")
            password = os.getenv("MY_PASSWORD")
            sender_name = "🔔Notifier"
            formatted_from = formataddr((sender_name, my_email))
            connection.starttls()
            connection.login(user=my_email, password=password)
            subject = "Subject: New Arrival(s) in Urgoo\n\n"
            message = subject + combined_text
            connection.sendmail(
                from_addr=formatted_from,
                to_addrs="chster21@gmail.com",
                msg=message.encode("utf-8")
            )
            print(f"Email has been sent successfully.")
    else:
        print("There are no matched movies screening in theaters today.")

if __name__ == "__main__":
    movie_links = movie_extract()
    print(movie_links)
    movie_info(movie_links)
    # movie_tracker(currently_showing_list)

 
