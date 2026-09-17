#!/usr/bin/env python3
"""Urgoo Cinema scraper.

urgoo.mn redirects to new.urgoo.mn (a Next.js app). Movie links must be built on
new.urgoo.mn: urgoo.mn/movies/... redirects to the old www server and 404s.
The pages are server rendered, so plain HTTP is enough: no browser needed.

Flow: movie_extract() reads the homepage cards, both "Яг одоо дэлгэцнээ" (now
showing) and "Тун удахгүй" (coming soon); scrape_schedule() reads the /schedule
page, whose flight payload holds every screening on every date the cinema has
opened for sale (advance sales months ahead included), each with a direct
seat-selection link; movie_info() reads each movie page for the details.
scrape() runs all three and returns common movie records.
"""

import datetime
import json
import re
import sys
import time

from bs4 import BeautifulSoup

from common import clean_text, fetch_html, flight_payload, json_after, local_datetime, new_movie, showtime

CINEMA = "Urgoo"
BASE_URL = "https://new.urgoo.mn"
# Homepage sections: "now-showing" (Яг одоо дэлгэцнээ) and "coming-soon" (Тун удахгүй)
SECTION_IDS = ("now-showing", "coming-soon")

# Ratings seen on the site: G, PG, PG13, R, R16 ... (also accept R18, NC-17, 16+)
RATING_PATTERN = re.compile(r'^(G|PG|PG-?13|R(-?\d{2})?|NC-?17|\d{1,2}\+)$', re.IGNORECASE)


def absolute(href):
    return href if href.startswith("http") else BASE_URL + href


def movie_extract():
    """Return [{source_id, title, url, poster}] for the now-showing and coming-soon cards."""
    soup = BeautifulSoup(fetch_html(BASE_URL + "/"), "html.parser")
    movies, seen = [], set()
    for section_id in SECTION_IDS:
        section = soup.find(id=section_id)
        if section is None:
            print(f"❌ Urgoo: no '{section_id}' section on the homepage")
            continue
        for card in section.select("a[href*='/movies/']"):
            match = re.search(r"/movies/([^/?#]+)", card["href"])
            # Each card has a blurred aria-hidden placeholder <img> first; the real
            # poster is the first Next.js fill image and carries the title as alt.
            poster = card.select_one("img[data-nimg='fill']")
            if not match or poster is None or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            movies.append({
                "source_id": match.group(1),
                "title": clean_text(poster.get("alt", "")),
                "url": absolute(card["href"]),
                "poster": poster.get("src", ""),
            })
    return movies


def parse_movie_page(html, link):
    soup = BeautifulSoup(html, "html.parser")
    # Some pages have no <h1>; fall back to the og:title / <title>, which is just "Urgoo"
    # on a bare page, and only then to the listing's title (its Cyrillic can be garbled).
    heading = next((h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)), "")
    if not heading:
        og_title = soup.find("meta", property="og:title")
        heading = clean_text(og_title["content"] if og_title and og_title.get("content")
                             else (soup.title.string if soup.title and soup.title.string else ""))
    if not heading or heading.lower() == CINEMA.lower():
        heading = link["title"]
    # The raw HTML has empty loading skeletons of the info box before the streamed-in real one.
    paragraph = soup.select_one("div[class~='bg-foreground/5'][class~='rounded-lg'] > p")
    meta_description = soup.find("meta", attrs={"name": "description"})
    description = (paragraph.get_text(" ", strip=True) if paragraph
                   else meta_description.get("content", "") if meta_description else "")

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
    return new_movie(CINEMA, link["source_id"], heading, link["url"],
                     poster=poster, description=description, **details)


def fetch_movie_page(url):
    """The site answers with a bare page (no details, titled just "Urgoo") when it is
    asked too quickly, so pages are read one at a time and a bare one is retried once."""
    html = fetch_html(url)
    if "data-slot=\"info-row\"" not in html:
        time.sleep(3)
        html = fetch_html(url)
    return html


def movie_info(links):
    """Read each movie page and return common movie records (without showtimes)."""
    movies = []
    for link in links:
        try:
            movies.append(parse_movie_page(fetch_movie_page(link["url"]), link))
            print(f"Urgoo: scraped {link['url']}")
        except Exception as e:  # keep the film (and its screenings) with what the listing says
            print(f"⚠️ Urgoo: error on {link['url']}: {e}")
            movies.append(new_movie(CINEMA, link["source_id"], link["title"], link["url"], poster=link["poster"]))
    return movies


def scrape_schedule():
    """Return ({movie_id: [showtime, ...]}, {movie_id: link}) for every date on /schedule."""
    films = json_after(flight_payload(fetch_html(BASE_URL + "/schedule")), '"films":',
                       lambda v: isinstance(v, list) and all(isinstance(f, dict) and "showtimes" in f for f in v))
    if films is None:
        raise RuntimeError("Urgoo: no film list found on /schedule")
    today = datetime.date.today()
    sessions, links = {}, {}
    for film in films:
        movie_id = film["filmId"]
        url = f"{BASE_URL}/movies/{movie_id}"
        links[movie_id] = {"source_id": movie_id, "title": film.get("title", ""), "url": url,
                           "poster": film.get("posterUrl") or ""}
        for show in film.get("showtimes") or []:
            start = local_datetime(show.get("startsAt"))
            if start is None or start.date() < today:
                continue
            # The site shows start + running time as the end of the screening.
            end = start + datetime.timedelta(minutes=film["runtimeMinutes"]) if film.get("runtimeMinutes") else None
            sessions.setdefault(movie_id, []).append(showtime(
                start.date().isoformat(), show.get("cinemaName", ""), start.strftime("%H:%M"),
                hall=show.get("screenName") or "", end_time=end.strftime("%H:%M") if end else "",
                fmt=" ".join(show.get("attributes") or []), url=f"{url}/sessions/{show['id']}/seats",
                available=show.get("seatsAvailable", 1) > 0,
            ))
    return sessions, links


def scrape():
    """Full Urgoo run: now-showing and coming-soon movies with details and all screenings."""
    links = movie_extract()
    print(f"Urgoo: {len(links)} movies on the homepage")
    sessions, scheduled = scrape_schedule()
    print(f"Urgoo: {sum(len(v) for v in sessions.values())} screenings on "
          f"{len({s['date'] for v in sessions.values() for s in v})} dates")
    # Films that have screenings but are in neither homepage grid still deserve an entry.
    known = {link["source_id"] for link in links}
    extra = [link for movie_id, link in scheduled.items() if movie_id not in known and movie_id in sessions]
    if extra:
        print(f"Urgoo: {len(extra)} more films found in the schedule")
    movies = movie_info(links + extra)
    for movie in movies:
        movie["showtimes"] = sessions.get(movie["source_id"], [])
    return movies


if __name__ == "__main__":
    result = scrape()
    for m in result:
        print(f"- {m['title']} | {m['rating']} | {m['duration']} | opens {m['start_date']} | {len(m['showtimes'])} screenings")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
