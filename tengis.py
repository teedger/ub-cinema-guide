#!/usr/bin/env python3
"""Tengis cinema scraper (www.tengis.mn, Next.js).

movie_extract() lists the films in the homepage #movies grid, movie_info() reads
each film page: details plus the full schedule (branch -> date -> times). Tengis
has no per-screening booking link, so showtimes link to the film page.
"""

import json
import re
import sys
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common import clean_text, make_driver, new_movie, showtime

CINEMA = "Tengis"
BASE_URL = "https://www.tengis.mn"
TIME_PATTERN = re.compile(r"^(\d{1,2}:\d{2})\s*(.*)$")


def absolute(href):
    return href if href.startswith("http") else BASE_URL + href


def poster_url(img):
    """Next.js serves posters through /_next/image?url=<encoded original>."""
    src = img.get("src", "") if img else ""
    if "/_next/image" in src:
        original = parse_qs(urlsplit(src).query).get("url")
        if original:
            return original[0]
    return absolute(src) if src else ""


def movie_extract(driver=None):
    """Return [{source_id, title, url, poster}] for the films in the #movies grid."""
    own_driver = driver is None
    driver = driver or make_driver()
    movies, seen = [], set()
    try:
        driver.get(BASE_URL + "/")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#movies a[href^='/film/']"))
        )
        section = BeautifulSoup(driver.page_source, "html.parser").find(id="movies")
        for card in section.select(".group"):
            title_link = card.select_one("a.block[href^='/film/']") or card.select_one("a[href^='/film/']")
            if title_link is None or title_link["href"] in seen:
                continue
            seen.add(title_link["href"])
            movies.append({
                "source_id": title_link["href"].rsplit("/", 1)[-1],
                "title": clean_text(title_link.get("title") or title_link.get_text(" ", strip=True)),
                "url": absolute(title_link["href"]),
                "poster": poster_url(card.find("img")),
            })
    except TimeoutException:
        print("❌ Tengis: the #movies grid never appeared")
    finally:
        if own_driver:
            driver.quit()
    return movies


def parse_film_page(html, link):
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("div.container.my-10") or soup
    heading = container.find("h1")
    title = heading.get_text(" ", strip=True) if heading else link["title"]

    rating_el = container.select_one("div.absolute.left-4.top-4 span")
    genres = [s.get_text(" ", strip=True) for s in container.select("div.absolute.bottom-4 span")]
    poster_img = container.select_one("div[class*='aspect-[3/4]'] img") or container.find("img")

    details = {"duration": "", "start_date": "", "description": ""}
    for p in container.select("ul.flex.flex-col.gap-2 li p"):
        label_el = p.find("span")
        label = label_el.get_text(strip=True) if label_el else ""
        value = clean_text(p.get_text(" ", strip=True).replace(label, "", 1))
        if label.startswith("Үргэлжлэх хугацаа"):
            details["duration"] = value
        elif label.startswith("Нээлтийн огноо"):
            details["start_date"] = value
        elif label.startswith("Танилцуулга"):
            details["description"] = value

    movie = new_movie(CINEMA, link["source_id"], title, link["url"],
                      poster=poster_url(poster_img) or link.get("poster", ""),
                      genres=genres, rating=rating_el.get_text(strip=True) if rating_el else "",
                      **details)

    # Schedule list: <li><p class="text-xl">branch</p></li> followed by one
    # <li><p class="mb-4">date</p> ...time chips...</li> per date.
    branch = ""
    for li in container.select("ul.flex.flex-col.gap-4 > li"):
        branch_el = li.select_one("p.text-xl")
        date_el = li.select_one("p.mb-4")
        if branch_el is not None:
            branch = branch_el.get_text(strip=True)
            continue
        if date_el is None:
            continue
        date = date_el.get_text(strip=True)
        for chip in li.select("span"):
            match = TIME_PATTERN.match(chip.get_text(" ", strip=True))
            if not match:
                continue
            movie["showtimes"].append(showtime(
                date, branch, match.group(1), fmt=match.group(2), url=link["url"],
                available="cursor-not-allowed" not in " ".join(chip.get("class", [])),
            ))
    return movie


def movie_info(links, driver=None):
    own_driver = driver is None
    driver = driver or make_driver()
    movies = []
    try:
        for link in links:
            try:
                driver.get(link["url"])
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.container.my-10 h1"))
                )
                movies.append(parse_film_page(driver.page_source, link))
                print(f"Tengis: scraped {link['url']}")
            except TimeoutException:
                print(f"❌ Tengis: film page never loaded: {link['url']}")
            except Exception as e:
                print(f"⚠️ Tengis: error on {link['url']}: {e}")
    finally:
        if own_driver:
            driver.quit()
    return movies


def scrape():
    driver = make_driver()
    try:
        links = movie_extract(driver)
        print(f"Tengis: {len(links)} films listed")
        return movie_info(links, driver)
    finally:
        driver.quit()


if __name__ == "__main__":
    result = scrape()
    for m in result:
        print(f"- {m['title']} | {m['rating']} | {m['duration']} | {len(m['showtimes'])} screenings")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
