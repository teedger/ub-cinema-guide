#!/usr/bin/env python3
"""Tengis cinema scraper (www.tengis.mn, Next.js).

The homepage is statically rendered and carries everything as JSON in
__NEXT_DATA__, so plain HTTP is enough: no browser needed.

    ongoings       one entry per schedule tab (today, tomorrow, pre-order day), each
                   with its films and their sessions in both theatres
    preorderings   films whose tickets are already on sale before they open
    upcomings      announced films: opening date only, no sessions yet

A film showing in both theatres exists twice on the site under one slug (the
Гэгээнтэн copy is a child of the Тэнгис 1 film), so records are keyed by slug.
Tengis has no per-screening booking link, so showtimes link to the film page.
"""

import json
import re
import sys

from common import duration_text, fetch_html, local_datetime, new_movie, next_data, showtime

CINEMA = "Tengis"
BASE_URL = "https://www.tengis.mn"
# Listed like a film but not one: "Танхим түрээс" is the hall-rental service.
NOT_A_FILM = re.compile(r"түрээс", re.IGNORECASE)


def absolute(href):
    return href if href.startswith("http") else BASE_URL + href


def poster_url(path):
    """Absolute poster URL; the site stores the text 'undefined' for films without one."""
    path = path or ""
    return absolute(path) if path.startswith(("/", "http")) else ""


def page_repo(url):
    repo = next_data(fetch_html(url)).get("props", {}).get("pageProps", {}).get("repo")
    if not repo:
        raise RuntimeError(f"Tengis: no page data found on {url}")
    return repo


def is_film(film):
    if NOT_A_FILM.search(film.get("title") or ""):
        print(f"Tengis: skipping non-film listing '{film['title']}'")
        return False
    return True


def film_record(film):
    opening = local_datetime(film.get("openDate") or film.get("nationalOpenDate"))
    genres = [(g.get("genre") or {}).get("translated") or (g.get("genre") or {}).get("title") for g in film.get("genres") or []]
    return new_movie(CINEMA, film["slug"], film["title"], f"{BASE_URL}/film/{film['slug']}",
                     poster=poster_url(film.get("verticalPosterUrl")),
                     description=film.get("description"), genres=genres,
                     duration=duration_text(film.get("duration")), rating=film.get("rating") or "",
                     start_date=opening.date().isoformat() if opening else "")


def session_showtime(session, branch, url):
    start = local_datetime(session.get("showTime"))
    if start is None:
        return None
    labels = list(session.get("attributes") or [])
    labels += [name for flag, name in (("isVip", "VIP"), ("isPremium", "Premium")) if session.get(flag)]
    # The site greys out DELETED sessions: they have started or were withdrawn.
    return showtime(start.date().isoformat(), branch, start.strftime("%H:%M"), hall=session.get("screenName") or "",
                    fmt=" ".join(labels), url=url,
                    available=session.get("status") == "ENABLED" and not session.get("soldOut"))


def film_page_sessions(slug, theatre_names):
    """[(session, branch)] from a film page: the film's own sessions plus its other-theatre copies'."""
    film = page_repo(f"{BASE_URL}/film/{slug}").get("movie") or {}
    found = []
    for copy in [film] + list(film.get("children") or []):
        branch = theatre_names.get(copy.get("movieTheatreId"), "")
        found += [(session, branch) for session in copy.get("sessions") or []]
    return found


def scrape():
    repo = page_repo(BASE_URL + "/")
    theatre_names = {t["id"]: t["title"] for t in repo.get("theatres") or []}
    movies, seen_sessions = {}, set()

    def add_sessions(movie, sessions):
        for session, branch in sessions:
            show = session_showtime(session, branch, movie["url"])
            if show is not None and session.get("id") not in seen_sessions:
                seen_sessions.add(session.get("id"))
                movie["showtimes"].append(show)

    for day in repo.get("ongoings") or []:
        for film in day.get("movies") or []:
            if not is_film(film):
                continue
            movie = movies.setdefault(film["slug"], film_record(film))
            add_sessions(movie, [(session, theatre.get("title", ""))
                                 for theatre in film.get("theatres") or [] for session in theatre.get("sessions") or []])
    for film in (repo.get("preorderings") or []) + (repo.get("upcomings") or []):
        if not is_film(film):
            continue
        movie = movies.setdefault(film["slug"], film_record(film))
        if film.get("type") == "PREORDERING" and not movie["showtimes"]:
            # On sale but not under any homepage tab: the film page has the sessions.
            try:
                add_sessions(movie, film_page_sessions(film["slug"], theatre_names))
            except Exception as e:
                print(f"⚠️ Tengis: no sessions for {film['title']}: {e}")

    print(f"Tengis: {len(movies)} films listed, {sum(1 for m in movies.values() if not m['showtimes'])} of them coming soon")
    return list(movies.values())


if __name__ == "__main__":
    result = scrape()
    for m in result:
        print(f"- {m['title']} | {m['rating']} | {m['duration']} | opens {m['start_date']} | {len(m['showtimes'])} screenings")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
