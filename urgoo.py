#!/usr/bin/env python3
"""Urgoo Cinema scraper.

urgoo.mn redirects to new.urgoo.mn (a Next.js app). Movie links must be built on
new.urgoo.mn: urgoo.mn/movies/... redirects to the old www server and 404s.

Flow: movie_extract() reads the "Яг одоо дэлгэцнээ" (now showing) cards on the
homepage, movie_info() reads each movie page for details, and scrape_schedule()
walks the /schedule page date by date to collect every screening with its direct
seat-selection link. scrape() runs all three and returns common movie records.
"""

import datetime
import json
import re
import sys
import time

from bs4 import BeautifulSoup
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common import clean_text, date_from_month_day, make_driver, new_movie, showtime

CINEMA = "Urgoo"
BASE_URL = "https://new.urgoo.mn"
# Homepage sections: "now-showing" (Яг одоо дэлгэцнээ) and "coming-soon" (Тун удахгүй)
SECTION_ID = "now-showing"
MAX_DAYS_AHEAD = 7

# Ratings seen on the site: G, PG, PG13, R, R16 ... (also accept R18, NC-17, 16+)
RATING_PATTERN = re.compile(r'^(G|PG|PG-?13|R(-?\d{2})?|NC-?17|\d{1,2}\+)$', re.IGNORECASE)
TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")


def absolute(href):
    return href if href.startswith("http") else BASE_URL + href


def close_floating_ad(driver, wait_seconds=3):
    """Dismiss the floating ad dialog if one shows up; never block if it doesn't."""
    try:
        presentation = WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='presentation']"))
        )
        presentation.find_element(By.TAG_NAME, "svg").click()
        print("Clicked X on a floating ad!")
    except (TimeoutException, NoSuchElementException):
        pass


def movie_extract(driver=None):
    """Return [{source_id, title, url, poster}] for the now-showing cards."""
    own_driver = driver is None
    driver = driver or make_driver()
    movies = []
    try:
        driver.get(BASE_URL + "/")
        close_floating_ad(driver)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, SECTION_ID)))
        section = BeautifulSoup(driver.page_source, "html.parser").find(id=SECTION_ID)
        for card in section.select("a[href*='/movies/']"):
            match = re.search(r"/movies/([^/?#]+)", card["href"])
            # Each card has a blurred aria-hidden placeholder <img> first; the real
            # poster is the first Next.js fill image and carries the title as alt.
            poster = card.select_one("img[data-nimg='fill']")
            if not match or poster is None:
                continue
            movies.append({
                "source_id": match.group(1),
                "title": clean_text(poster.get("alt", "")),
                "url": absolute(card["href"]),
                "poster": poster.get("src", ""),
            })
    except TimeoutException:
        print(f"❌ Urgoo: the '{SECTION_ID}' section never appeared")
    finally:
        if own_driver:
            driver.quit()
    return movies


def parse_movie_page(html, link):
    soup = BeautifulSoup(html, "html.parser")
    # Some pages (pre-orders) have no <h1>; fall back to the og:title / <title>.
    heading = next((h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)), "")
    if not heading:
        og_title = soup.find("meta", property="og:title")
        heading = clean_text(og_title["content"] if og_title and og_title.get("content")
                             else (soup.title.string if soup.title and soup.title.string else ""))
    info_box = soup.select_one("div[class~='bg-foreground/5'][class~='rounded-lg']")
    description = ""
    if info_box is not None:
        paragraph = info_box.find("p")
        description = paragraph.get_text(" ", strip=True) if paragraph else ""

    details = {"genres": [], "duration": "", "rating": "", "start_date": ""}
    # Info rows: Хугацаа / Өргөөгийн дэлгэцнээ / IMDb үнэлгээ / <rating> / Найруулагч / Төрөл
    for row in soup.select("[data-slot='info-row']"):
        key_el = row.select_one("[data-slot='info-row-title']")
        val_el = row.select_one("[data-slot='info-row-description']")
        key = key_el.get_text(strip=True) if key_el else ""
        value = val_el.get_text(" ", strip=True) if val_el else ""
        if key == "Төрөл":
            details["genres"] = [g.strip() for g in value.split(",") if g.strip()]
        elif key == "Хугацаа":
            details["duration"] = value
        elif key == "Өргөөгийн дэлгэцнээ":
            details["start_date"] = value
        elif RATING_PATTERN.match(key):
            details["rating"] = key

    poster = link.get("poster", "")
    if not poster:
        og = soup.find("meta", property="og:image")
        poster = og["content"] if og and og.get("content") else ""
    return new_movie(CINEMA, link["source_id"], heading or link["title"], link["url"],
                     poster=poster, description=description, **details)


def movie_info(links, driver=None):
    """Visit each movie page and return common movie records (without showtimes)."""
    own_driver = driver is None
    driver = driver or make_driver()
    movies = []
    try:
        for link in links:
            try:
                driver.get(link["url"])
                close_floating_ad(driver)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-slot='info-row']"))
                )
                movies.append(parse_movie_page(driver.page_source, link))
                print(f"Urgoo: scraped {link['url']}")
            except TimeoutException:
                print(f"❌ Urgoo: info box never appeared on {link['url']}; skipping")
            except Exception as e:  # keep going with the other movies
                print(f"⚠️ Urgoo: error on {link['url']}: {e}")
    finally:
        if own_driver:
            driver.quit()
    return movies


def _date_buttons(driver):
    return [b for b in driver.find_elements(By.CSS_SELECTOR, "button")
            if re.search(r"\d{1,2}\s*сар\s*\d{1,2}", b.text)]


def _session_hrefs(driver):
    return driver.execute_script(
        "return Array.from(document.querySelectorAll(\"a[href*='/sessions/']\")).map(a => a.getAttribute('href'))")


def _wait_for_new_sessions(driver, before, timeout=8):
    """After a date click, wait until the session list changed and then settled."""
    end = time.time() + timeout
    current = before
    while time.time() < end:
        current = _session_hrefs(driver)
        if current != before:
            break
        time.sleep(0.3)
    else:
        print("⚠️ Urgoo: schedule did not change after clicking a date; using what is shown")
    # The list can render empty first and fill in a moment later.
    for _ in range(10):
        time.sleep(0.4)
        again = _session_hrefs(driver)
        if again == current:
            break
        current = again


def parse_schedule_page(html, date):
    """Return {movie_id: [showtime, ...]} for the currently selected date."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("main") or soup
    sessions = {}
    for row in root.select("div[class~='divide-y'] > div"):
        poster_link = row.select_one("a[href*='/movies/']")
        match = re.search(r"/movies/([^/?#]+)", poster_link["href"]) if poster_link else None
        if not match:
            continue
        movie_id = match.group(1)
        for block in row.select("div[class~='space-y-3']"):
            name_el = block.find("p")
            branch = name_el.get_text(strip=True) if name_el else ""
            for a in block.select("a[href*='/sessions/']"):
                # A card shows [hall, start, end]; some cards omit the hall label.
                spans = [s.get_text(strip=True) for s in a.find_all("span")]
                times = [t for t in spans if TIME_PATTERN.match(t)]
                labels = [t for t in spans if t and not TIME_PATTERN.match(t)]
                if not times:
                    continue
                sessions.setdefault(movie_id, []).append(showtime(
                    date, branch, times[0], hall=labels[0] if labels else "",
                    end_time=times[1] if len(times) > 1 else "",
                    url=absolute(a["href"]),
                ))
    return sessions


def scrape_schedule(driver=None, max_days=MAX_DAYS_AHEAD):
    """Walk the /schedule page's date buttons and collect every screening."""
    own_driver = driver is None
    driver = driver or make_driver()
    today = datetime.date.today()
    sessions = {}
    try:
        driver.get(BASE_URL + "/schedule")
        close_floating_ad(driver)
        WebDriverWait(driver, 15).until(lambda d: _date_buttons(d))
        for index in range(len(_date_buttons(driver))):
            buttons = _date_buttons(driver)  # re-find: the DOM re-renders after each click
            if index >= len(buttons):
                break
            button = buttons[index]
            match = re.search(r"(\d{1,2})\s*сар\s*(\d{1,2})", button.text)
            date = date_from_month_day(int(match.group(1)), int(match.group(2)), today)
            if date < today or (date - today).days > max_days:
                continue
            if "border-brand-blue" not in (button.get_attribute("class") or ""):
                before = _session_hrefs(driver)
                driver.execute_script("arguments[0].click()", button)
                _wait_for_new_sessions(driver, before)
            day = parse_schedule_page(driver.page_source, date)
            print(f"Urgoo: {date} -> {sum(len(v) for v in day.values())} screenings")
            for movie_id, shows in day.items():
                sessions.setdefault(movie_id, []).extend(shows)
    except TimeoutException:
        print("❌ Urgoo: schedule page never showed its date buttons")
    finally:
        if own_driver:
            driver.quit()
    return sessions


def scrape():
    """Full Urgoo run: now-showing movies with details and all screenings."""
    driver = make_driver()
    try:
        links = movie_extract(driver)
        print(f"Urgoo: {len(links)} movies now showing")
        movies = movie_info(links, driver)
        sessions = scrape_schedule(driver)
        # Films that have screenings this week but are not in the now-showing
        # grid (pre-orders / previews) still deserve an entry.
        known = {link["source_id"] for link in links}
        extra = [{"source_id": movie_id, "title": "", "url": f"{BASE_URL}/movies/{movie_id}", "poster": ""}
                 for movie_id in sessions if movie_id not in known]
        if extra:
            print(f"Urgoo: {len(extra)} more films found in the schedule")
            movies += movie_info(extra, driver)
    finally:
        driver.quit()
    for movie in movies:
        movie["showtimes"] = sessions.get(movie["source_id"], [])
    return movies


if __name__ == "__main__":
    result = scrape()
    for m in result:
        print(f"- {m['title']} | {m['rating']} | {m['duration']} | {len(m['showtimes'])} screenings")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
