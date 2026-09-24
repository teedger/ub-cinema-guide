#!/usr/bin/env python3
"""Prime Cineplex scraper (www.primecineplex.mn).

The homepage has one jQuery-UI tab per day (today and tomorrow). Every tab lists
each film once with its branches and time links; each time link goes straight to
the seat-selection page and carries the show's metadata in its query string.
The tabs are in the server-rendered HTML, so plain HTTP is enough: no browser needed.

/Home/Upcoming is plain server-rendered HTML listing the announced films with
their release dates. Prime sells no advance tickets, so those have no showtimes.
"""

import datetime
import json
import re
import sys
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from common import clean_text, fetch_complete, fetch_html, new_movie, showtime

CINEMA = "Prime Cineplex"
BASE_URL = "https://www.primecineplex.mn"
UPCOMING_URL = BASE_URL + "/Home/Upcoming"
TIME_PATTERN = re.compile(r"^(\d{1,2}:\d{2})\s*(.*)$")
# Legend printed under every film on the site.
HALL_NAMES = {"G": "General", "AT": "Atmos", "P": "Premium", "VIP": "VIP",
              "PC": "Premium & Couple", "4DX": "4DX", "R": "Regular"}


def absolute(href):
    return href if href.startswith("http") else BASE_URL + href


def clean_booking_url(href):
    """Re-encode the booking URL's query string. The site emits raw spaces and
    literal '+' (e.g. 'PG 6+') in query values; without encoding, the server
    decodes '+' as a space."""
    parts = urlsplit(href)
    pairs = parse_qsl(parts.query.replace("+", "%2B"))
    query = urlencode(pairs, quote_via=quote)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def booking_params(href):
    return dict(parse_qsl(urlsplit(href).query.replace("+", "%2B")))


def parse_homepage(html):
    soup = BeautifulSoup(html, "html.parser")
    movies, seen_shows = {}, set()
    # One <div id="tab_N" class="tab-content"> per day; jQuery UI adds ui-tabs-panel in a browser.
    for panel in soup.select("div[id^='tab_'], div.ui-tabs-panel"):
        grid = panel.select_one("div.three.column.grid")
        if grid is None:
            continue
        # The grid and the inner card wrapper both carry the "column" class, so
        # only direct children are real film cards.
        for card in grid.find_all("div", class_="column", recursive=False):
            name_el = card.select_one("div.col-7")
            meta_el = card.select_one("div.col-5")
            detail_link = card.select_one("a[href*='GetMovieDetails']")
            if name_el is None or detail_link is None:
                continue
            event_id = re.search(r"EventID=(\d+)", detail_link["href"], re.I)
            event_id = event_id.group(1) if event_id else name_el.get_text(strip=True)
            meta = [clean_text(part) for part in meta_el.get_text(" ", strip=True).split("/")] if meta_el else []
            fmt, rating, duration = (meta + ["", "", ""])[:3]
            poster = card.select_one("img#samloadimage") or card.find("img")

            movie = movies.get(event_id)
            if movie is None:
                # GetMovieDetails only renders inside the site's lightbox, so the
                # homepage (where the schedule lives) is the useful movie link.
                movie = new_movie(CINEMA, event_id, name_el.get_text(" ", strip=True),
                                  BASE_URL + "/",
                                  poster=poster.get("src", "") if poster else "",
                                  duration=duration, rating=rating)
                movie["format"] = fmt
                movies[event_id] = movie

            schedule = card.select_one("div.col-8")
            for branch_div in (schedule.find_all("div", recursive=False) if schedule else []):
                inner = branch_div.find_all("div", recursive=False)
                branch = inner[0].get_text(" ", strip=True) if inner else ""
                for a in branch_div.select("a[href*='ShoppingCart']"):
                    params = booking_params(a["href"])
                    show_id = params.get("ShowID")
                    if show_id in seen_shows:
                        continue
                    seen_shows.add(show_id)
                    match = TIME_PATTERN.match(a.get_text(" ", strip=True))
                    time_text = match.group(1) if match else a.get_text(strip=True)
                    hall_code = match.group(2).strip() if match else params.get("AuditoriumName", "")
                    if not movie["genres"] and params.get("Genre"):
                        movie["genres"] = [g.strip() for g in params["Genre"].split(",") if g.strip()]
                    movie["showtimes"].append(showtime(
                        params.get("ShowDate", ""), params.get("TheatreName") or branch, time_text,
                        hall=HALL_NAMES.get(hall_code, hall_code),
                        fmt=params.get("ShowCategory", fmt),
                        url=clean_booking_url(absolute(a["href"])),
                        available=params.get("occupancy", "").lower() not in ("sold out", "soldout"),
                    ))
    return list(movies.values())


def parse_upcoming(html):
    """Cards on /Home/Upcoming: label/value rows (Title, Type '2D - PG13 13+',
    Release Date 'Fri, 18 Sep 2026', Duration '111 mins', Genre)."""
    movies = []
    for card in BeautifulSoup(html, "html.parser").select("div.column.sammoviemousehover"):
        labels = [clean_text(el.get_text(" ", strip=True)) for el in card.select(".comingsoon_title")]
        values = [clean_text(el.get_text(" ", strip=True)).lstrip(":").strip() for el in card.select("[class*='comingsoon_des']")]
        info = dict(zip(labels, values))
        detail_link = card.select_one("a[href*='EventID']")
        if not info.get("Title") or detail_link is None:
            continue
        event_id = re.search(r"EventID=(\d+)", detail_link["href"], re.I)
        fmt, _, rating = info.get("Type", "").partition(" - ")
        try:
            release = datetime.datetime.strptime(info.get("Release Date", ""), "%a, %d %b %Y").date().isoformat()
        except ValueError:
            release = ""
        poster = card.find("img")
        movie = new_movie(CINEMA, event_id.group(1) if event_id else info["Title"], info["Title"], UPCOMING_URL,
                          poster=poster.get("src", "") if poster else "", duration=info.get("Duration", ""),
                          genres=[g for g in info.get("Genre", "").split(",")], rating=rating, start_date=release)
        movie["format"] = fmt
        movies.append(movie)
    return movies


def scrape_upcoming():
    try:
        return parse_upcoming(fetch_html(UPCOMING_URL))
    except Exception as e:  # the day's schedule matters more than the announcements
        print(f"⚠️ Prime Cineplex: could not read the upcoming films: {e}")
        return []


def scrape():
    movies = parse_homepage(fetch_complete(BASE_URL + "/", lambda html: bool(parse_homepage(html)), CINEMA))
    if not movies:
        print("❌ Prime Cineplex: no film tabs on the homepage")
    # A film that opens tomorrow can be in both lists: keep the one with the showtimes.
    showing = {m["source_id"] for m in movies}
    upcoming = [m for m in scrape_upcoming() if m["source_id"] not in showing]
    print(f"Prime Cineplex: {len(movies)} films listed, {len(upcoming)} coming soon")
    return movies + upcoming


# Kept for callers that used the old two-step name.
movie_extract = scrape


if __name__ == "__main__":
    result = scrape()
    for m in result:
        print(f"- {m['title']} | {m['rating']} | {m['duration']} | opens {m['start_date']} | {len(m['showtimes'])} screenings")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
