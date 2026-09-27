#!/usr/bin/env python3
"""The year's top 10 films by worldwide box office, from Box Office Mojo.

    python boxoffice.py       # fetch and save output/boxoffice.json

Reads Box Office Mojo's worldwide chart for the current year, sorts it by
worldwide gross, and fetches each top-10 film's pages for its poster, synopsis,
genres, running time, rating and release date.
Early in January the new year's chart is nearly empty, so until it has ten
films the previous year's chart is used instead.

Films the cinema guide also lists get a `film_id` at build time (see
link_to_guide) so their poster opens the film's page with showtimes. The rest
get a `page_id` and a page of their own (see not_showing_films) that says no
Ulaanbaatar cinema is screening them.
"""

import datetime
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from common import OUTPUT_DIR, clean_text, fetch_html, normalize_date, parse_duration_minutes
from merge import slugify

MOJO = "https://www.boxofficemojo.com"
TOP_N = 10
BOXOFFICE_FILE = os.path.join(OUTPUT_DIR, "boxoffice.json")
ENGLISH = "en-US,en;q=0.9"  # Box Office Mojo localises dates and labels to the Accept-Language

ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
GROUP_LINK = re.compile(r'href="(/releasegroup/gr\d+/)')
# The small poster on a release group page; data-a-hires is the 2x version.
POSTER = re.compile(r'<img[^>]*src="(https://m\.media-amazon\.com/images/M/[^"]+)"')
IMDB_ID = re.compile(r'href="/title/(tt\d+)/')
SUMMARY = re.compile(r'<span class="a-size-medium">(.*?)</span>', re.S)
# The title page's "Summary Details": <div ...><span>Label</span><span>Value</span></div>
DETAIL = re.compile(r'<div class="a-section a-spacing-none"><span>\s*([^<]+?)\s*</span><span>(.*?)</span></div>', re.S)


def money(text):
    """'$2,480,707,775' -> 2480707775; '-' (no figure yet) -> 0."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def chart(year):
    """Every film on the worldwide chart for `year`, highest worldwide gross first."""
    page = fetch_html(f"{MOJO}/year/world/{year}/", language=ENGLISH)
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


def text_of(fragment):
    return clean_text(html.unescape(re.sub(r"<[^>]+>", " ", fragment)))


def title_details(imdb):
    """Synopsis and facts from the film's Box Office Mojo title page."""
    page = fetch_html(f"{MOJO}/title/{imdb}/", language=ENGLISH)
    facts = {label: value for label, value in DETAIL.findall(page)}
    summary = SUMMARY.search(page)
    release = text_of(facts.get("Earliest Release Date", ""))
    release = re.sub(r"\s*\(.*\)$", "", release)  # 'July 15, 2026 (EMEA, APAC)' -> 'July 15, 2026'
    try:
        release = datetime.datetime.strptime(release, "%B %d, %Y").date().isoformat()
    except ValueError:
        release = normalize_date(release)
    return {
        "description": text_of(summary.group(1)) if summary else "",
        # Genres come one per line: 'Action\n    \n    Adventure'
        "genres": [g for g in (clean_text(x) for x in html.unescape(re.sub(r"<[^>]+>", "", facts.get("Genres", ""))).split("\n")) if g],
        "rating": text_of(facts.get("MPAA", "")),
        "duration_minutes": parse_duration_minutes(text_of(facts.get("Running Time", "")).replace("hr", "h")),
        "release_date": release,
        "distributor": text_of(facts.get("Domestic Distributor", "").split("<br")[0]),
        "budget": money(text_of(facts.get("Budget", ""))),
    }


def add_details(film):
    """Poster and IMDb id from the release group page, then synopsis and facts from the title page.
    Whatever cannot be fetched stays empty: a missing detail must not lose the whole chart."""
    film.update({"poster": "", "imdb": "", "description": "", "genres": [], "rating": "", "duration_minutes": None,
                 "release_date": "", "distributor": "", "budget": 0})
    try:
        page = fetch_html(film["url"], language=ENGLISH)
        poster = POSTER.search(page)
        imdb = IMDB_ID.search(page)
        film["poster"] = poster_url(poster.group(1)) if poster else ""
        film["imdb"] = imdb.group(1) if imdb else ""
        if film["imdb"]:
            film.update(title_details(film["imdb"]))
    except Exception as e:
        print(f"⚠️ Box office: incomplete details for {film['title']}: {type(e).__name__}: {e}")
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
    with ThreadPoolExecutor(max_workers=5) as pool:  # two pages per film; Box Office Mojo can be slow
        top = list(pool.map(add_details, films[:TOP_N]))
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
    """Copy of `payload` where films the guide lists carry that film's `film_id`, and the
    rest a `page_id` for the page not_showing_films builds for them."""
    if not payload:
        return None
    ids = {}
    for m in movies:
        for title in [m["title"], *(m.get("titles") or {}).values()]:
            if title:
                ids.setdefault(title_key(title), m["id"])
    taken = {m["id"] for m in movies}
    films = []
    for f in payload["films"]:
        film_id = ids.get(title_key(f["title"]))
        page_id = None
        if not film_id:
            page_id = slugify(f["title"]) or f"top-{f['rank']}"
            if page_id in taken:  # a different film with the same slug is showing
                page_id += f"-{payload['year']}"
        films.append({**f, "film_id": film_id, "page_id": page_id})
    return {**payload, "films": films}


def not_showing_films(linked):
    """Film records, in the guide's shape, for the top-10 films no Ulaanbaatar cinema shows.
    `linked` is link_to_guide's result. They have no cinemas, so film.html shows a notice
    in place of the screenings, plus the box office figures."""
    if not linked:
        return []
    return [{
        "id": f["page_id"], "title": f["title"], "titles": {}, "poster": f.get("poster", ""),
        "description": f.get("description", ""), "genres": f.get("genres", []),
        "duration": "", "duration_minutes": f.get("duration_minutes"), "rating": f.get("rating", ""),
        "start_date": "", "cinemas": [], "dates": [], "showtime_count": 0,
        "box_office": {"rank": f["rank"], "year": linked["year"], "worldwide": f["worldwide"],
                       "domestic": f["domestic"], "international": f["international"], "url": f["url"],
                       "source": linked["source"], "scraped_at": linked["scraped_at"],
                       "release_date": f.get("release_date", ""), "distributor": f.get("distributor", ""),
                       "budget": f.get("budget", 0)},
    } for f in linked["films"] if f.get("page_id")]


def short_money(amount):
    """2480707775 -> '$2.48B', 684985304 -> '$685M', 374946 -> '$375K'."""
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.0f}M"
    return f"${amount / 1_000:.0f}K"


if __name__ == "__main__":
    data = top_films()
    save(data)
    for film in data["films"]:
        print(f"{film['rank']:>2}. {film['title']} · {short_money(film['worldwide'])}" + ("" if film["poster"] else " (no poster)"))
    sys.exit(0 if data["films"] else 1)
