#!/usr/bin/env python3
"""Skywing cinema scraper (www.tix.mn/theaters/skywing, Next.js).

Skywing sells its tickets through the tix.mn platform. The pages are server
rendered and carry their data as JSON inside the Next.js flight payload
(self.__next_f.push(...)), so plain HTTP is enough: no browser needed.

The theater page lists every film with all of its scheduled sessions, advance
sales included. Each film page adds the hall name and sold-out flag per session.
Every session has a direct seat-picker link: /checkout/<session id>/seats.

tix.mn hosts other theaters too (CinemaNext, United Cinema); scrape_theater()
works for any of them given the theater's slug.
"""

import json
import re
import sys
import urllib.request

from common import USER_AGENT, new_movie, showtime

CINEMA = "Skywing"
BASE_URL = "https://www.tix.mn"
THEATER_SLUG = "skywing"
BRANCH = "Зайсан"  # single location, north-east of Zaisan hill
FLIGHT_CHUNK = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)


def fetch_flight(url):
    """Download a page and return its Next.js flight payload as one string."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "mn,en;q=0.8"})
    for attempt in (1, 2):  # one retry: the pages are ~1 MB and occasionally time out
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                html = response.read().decode("utf-8", errors="replace")
            break
        except OSError:
            if attempt == 2:
                raise
    parts = []
    for chunk in FLIGHT_CHUNK.findall(html):
        try:
            item = json.loads(chunk)
        except ValueError:
            continue
        if len(item) > 1 and isinstance(item[1], str):
            parts.append(item[1])
    return "".join(parts)


def json_after(payload, marker, accept=lambda value: True):
    """Decode the JSON value that follows `marker`, trying each occurrence until
    one satisfies `accept`. Returns None when nothing fits."""
    decoder = json.JSONDecoder()
    for match in re.finditer(re.escape(marker), payload):
        try:
            value, _ = decoder.raw_decode(payload, match.end())
        except ValueError:
            continue
        if accept(value):
            return value
    return None


def theater_data(slug):
    """{"cinema": {...}, "movies": [{..., "sessions": [...]}, ...]} from the theater page."""
    payload = fetch_flight(f"{BASE_URL}/theaters/{slug}")
    data = json_after(payload, '"data":', lambda v: isinstance(v, dict) and "cinema" in v and "movies" in v)
    if data is None:
        raise RuntimeError(f"tix.mn: no film data found on /theaters/{slug}")
    return data


def session_details(film_url, cinema_id):
    """{session id: {screen_name, soldout_status, ...}} for one cinema, from a film page."""
    sessions = json_after(fetch_flight(film_url), '"sessions":',
                          lambda v: isinstance(v, list) and all(isinstance(s, dict) and "screen_name" in s for s in v))
    return {s["id"]: s for s in sessions or [] if s.get("cinema_id") == cinema_id}


def duration_text(minutes):
    if not minutes:
        return ""
    hours, mins = divmod(int(minutes), 60)
    return f"{hours} цаг {mins} мин" if hours else f"{mins} мин"


def plain(text):
    """Flight payloads replace long strings with "$12"-style references; drop those."""
    return "" if str(text or "").startswith("$") else text or ""


def scrape_theater(slug=THEATER_SLUG, cinema=CINEMA, branch=BRANCH):
    data = theater_data(slug)
    cinema_id = data["cinema"]["id"]
    print(f"{cinema}: {len(data['movies'])} films listed")
    movies = []
    for film in data["movies"]:
        url = f"{BASE_URL}/movies/{film['id']}?cinemaId={cinema_id}"
        movie = new_movie(cinema, film["id"], film["title"], url,
                          poster=plain(film.get("poster_image")), description=plain(film.get("synopsis")),
                          genres=film.get("genres"), duration=duration_text(film.get("runtime")),
                          rating=film.get("censorship") or "", start_date=(film.get("opening") or "")[:10])
        try:
            details = session_details(url, cinema_id)
        except Exception as e:  # the schedule is already known; only hall/sold-out is lost
            print(f"⚠️ {cinema}: no session details for {film['title']}: {e}")
            details = {}
        for session in film.get("sessions") or []:
            # start_time is local time, e.g. 2026-09-17T21:05:00. After-midnight shows are
            # filed under their real calendar date, not tix.mn's previous "business date".
            start, end = session.get("start_time") or "", session.get("end_time") or ""
            if len(start) < 16:
                continue
            extra = details.get(session["id"], {})
            hall = extra.get("screen_name") or ""
            movie["showtimes"].append(showtime(
                start[:10], branch, start[11:16], end_time=end[11:16],
                hall="" if hall.lower() == cinema.lower() else hall,  # the only hall is called "SkyWing"
                fmt=" ".join(tag["name"] for tag in session.get("tags") or [] if tag.get("name")),
                url=f"{BASE_URL}/checkout/{session['id']}/seats",
                available=not extra.get("soldout_status"),
            ))
        movies.append(movie)
        print(f"{cinema}: scraped {url} ({len(movie['showtimes'])} screenings)")
    return movies


def scrape():
    return scrape_theater()


if __name__ == "__main__":
    result = scrape()
    for m in result:
        print(f"- {m['title']} | {m['rating']} | {m['duration']} | {len(m['showtimes'])} screenings")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
