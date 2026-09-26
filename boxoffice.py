#!/usr/bin/env python3
"""The year's top 10 films by worldwide box office, from Box Office Mojo.

    python boxoffice.py       # fetch and save output/boxoffice.json

Reads Box Office Mojo's worldwide chart for the current year, sorts it by
worldwide gross, and fetches each top-10 film's page for its poster and IMDb id.
Early in January the new year's chart is nearly empty, so until it has ten
films the previous year's chart is used instead.

Films the cinema guide also lists get a `film_id` at build time (see
link_to_guide) so their poster opens the film's page with showtimes.
"""

import datetime
import html
import json
import os
import re
import sys

from common import OUTPUT_DIR, clean_text, fetch_html

MOJO = "https://www.boxofficemojo.com"
TOP_N = 10
BOXOFFICE_FILE = os.path.join(OUTPUT_DIR, "boxoffice.json")

ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
GROUP_LINK = re.compile(r'href="(/releasegroup/gr\d+/)')
# The small poster on a release group page; data-a-hires is the 2x version.
POSTER = re.compile(r'<img[^>]*src="(https://m\.media-amazon\.com/images/M/[^"]+)"')
IMDB_ID = re.compile(r'href="/title/(tt\d+)/')


def money(text):
    """'$2,480,707,775' -> 2480707775; '-' (no figure yet) -> 0."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def chart(year):
    """Every film on the worldwide chart for `year`, highest worldwide gross first."""
    page = fetch_html(f"{MOJO}/year/world/{year}/")
    films = []
    for row in ROW.findall(page):
        cells = CELL.findall(row)
        link = GROUP_LINK.search(row)
        if len(cells) < 6 or not link:  # the header row has <th> cells and no link
            continue
        text = [clean_text(html.unescape(re.sub(r"<[^>]+>", "", c))) for c in cells]
        films.append({"title": text[1], "worldwide": money(text[2]), "domestic": money(text[3]),
                      "international": money(text[5]), "url": MOJO + link.group(1)})
    # The chart is already in this order; sorting here keeps the ranking right even if it changes.
    films.sort(key=lambda f: f["worldwide"], reverse=True)
    return films


def poster_url(small):
    """IMDb image URLs carry their size after '._V1_'; ask for a 400px-wide copy instead."""
    return re.sub(r"\._V1_.*(\.\w+)$", r"._V1_SX400\1", small)


def add_details(film):
    """Poster and IMDb id from the film's release group page. Missing ones stay empty."""
    try:
        page = fetch_html(film["url"])
    except Exception as e:  # a missing poster must not lose the whole chart
        print(f"⚠️ Box office: no details for {film['title']}: {type(e).__name__}: {e}")
        page = ""
    poster = POSTER.search(page)
    imdb = IMDB_ID.search(page)
    film["poster"] = poster_url(poster.group(1)) if poster else ""
    film["imdb"] = imdb.group(1) if imdb else ""
    return film


def top_films(today=None):
    today = today or datetime.date.today()
    year = today.year
    films = chart(year)
    if len(films) < TOP_N:
        year -= 1
        films = chart(year)
    if not films:
        raise RuntimeError(f"Box Office Mojo's {year} worldwide chart had no films")
    top = [add_details(f) for f in films[:TOP_N]]
    for rank, film in enumerate(top, 1):
        film["rank"] = rank
    return {"scraped_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "year": year,
            "source": f"{MOJO}/year/world/{year}/", "films": top}


def save(payload):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(BOXOFFICE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved the {payload['year']} worldwide top {len(payload['films'])} to {BOXOFFICE_FILE}")


def load():
    """The last saved chart, or None when there is none (the site then leaves the section out)."""
    if not os.path.exists(BOXOFFICE_FILE):
        return None
    with open(BOXOFFICE_FILE, encoding="utf-8") as f:
        return json.load(f)


def title_key(title):
    return re.sub(r"[^\w]", "", title.lower())


def link_to_guide(payload, movies):
    """Copy of `payload` where films the guide lists carry that film's `film_id`."""
    if not payload:
        return None
    ids = {}
    for m in movies:
        for title in [m["title"], *(m.get("titles") or {}).values()]:
            if title:
                ids.setdefault(title_key(title), m["id"])
    films = [{**f, "film_id": ids.get(title_key(f["title"]))} for f in payload["films"]]
    return {**payload, "films": films}


def short_money(amount):
    """2480707775 -> '$2.48B', 684985304 -> '$685M'."""
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.2f}B"
    return f"${amount / 1_000_000:.0f}M"


if __name__ == "__main__":
    data = top_films()
    save(data)
    for film in data["films"]:
        print(f"{film['rank']:>2}. {film['title']} · {short_money(film['worldwide'])}" + ("" if film["poster"] else " (no poster)"))
    sys.exit(0 if data["films"] else 1)
