#!/usr/bin/env python3
"""tix.mn cinema scraper (Skywing and CinemaNext, Next.js).

Both cinemas sell their tickets through the tix.mn platform, so one scraper
serves them. The pages are server rendered and carry their data as JSON inside
the Next.js flight payload (self.__next_f.push(...)), so plain HTTP is enough:
no browser needed.

A theater page lists every film with all of its scheduled sessions, advance
sales included. Each film page adds the hall name and sold-out flag per session.
Every session has a direct seat-picker link: /checkout/<session id>/seats.

tix.mn hosts other theaters too; add one to CINEMAS and it is scraped like the
rest, given its slug from the /theaters/<slug> URL.
"""

import json
import sys

from common import duration_text, fetch_complete, fetch_html, flight_payload, json_after, new_movie, showtime

BASE_URL = "https://www.tix.mn"

# display name -> (theater slug, branch label). Both cinemas have a single location,
# so the branch names the neighbourhood the way the other scrapers' branches do.
CINEMAS = {
    "Skywing": ("skywing", "Зайсан"),            # north-east of Zaisan hill
    "CinemaNext": ("cinema_next", "16-р хороолол"),  # Bayanzurkh district, 16th micro-district
}


def fetch_flight(url):
    """Download a page and return its Next.js flight payload as one string."""
    return flight_payload(fetch_html(url))


def theater_data(slug):
    """{"cinema": {...}, "movies": [{..., "sessions": [...]}, ...]} from the theater page."""
    def film_data(html):
        return json_after(flight_payload(html), '"data":', lambda v: isinstance(v, dict) and "cinema" in v and "movies" in v)

    url = f"{BASE_URL}/theaters/{slug}"
    data = film_data(fetch_complete(url, lambda html: film_data(html) is not None, f"tix.mn {slug}"))
    if data is None:
        raise RuntimeError(f"tix.mn: no film data found on /theaters/{slug}")
    return data


def session_details(film_url, cinema_id):
    """{session id: {screen_name, soldout_status, ...}} for one cinema, from a film page."""
    sessions = json_after(fetch_flight(film_url), '"sessions":',
                          lambda v: isinstance(v, list) and all(isinstance(s, dict) and "screen_name" in s for s in v))
    return {s["id"]: s for s in sessions or [] if s.get("cinema_id") == cinema_id}


def plain(text):
    """Flight payloads replace long strings with "$12"-style references; drop those."""
    return "" if str(text or "").startswith("$") else text or ""


def scrape_theater(cinema):
    """Every film and screening at one tix.mn theater, as website movie records."""
    slug, branch = CINEMAS[cinema]
    data = theater_data(slug)
    cinema_id = data["cinema"]["id"]
    # Advance sales are normally part of "movies" already; keep any that are not.
    listed = {film["id"] for film in data["movies"]}
    films = data["movies"] + [f for f in data.get("advance_sale_movies") or [] if f["id"] not in listed]
    print(f"{cinema}: {len(films)} films listed")
    movies = []
    for film in films:
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
                hall="" if hall.lower() == cinema.lower() else hall,  # Skywing's only hall is called "SkyWing"
                fmt=" ".join(tag["name"] for tag in session.get("tags") or [] if tag.get("name")),
                url=f"{BASE_URL}/checkout/{session['id']}/seats",
                available=not extra.get("soldout_status"),
            ))
        movies.append(movie)
        print(f"{cinema}: scraped {url} ({len(movie['showtimes'])} screenings)")
    return movies


def scrape_skywing():
    return scrape_theater("Skywing")


def scrape_cinemanext():
    return scrape_theater("CinemaNext")


if __name__ == "__main__":
    result = [m for cinema in CINEMAS for m in scrape_theater(cinema)]
    for m in result:
        print(f"- {m['cinema']}: {m['title']} | {m['rating']} | {m['duration']} | {len(m['showtimes'])} screenings")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
