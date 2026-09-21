#!/usr/bin/env python3
"""Run every cinema scraper, merge the results into one entry per film and save
them for the website.

    python scraper_ultimate.py            # scrape all cinemas in parallel
    python scraper_ultimate.py --sequential
    python scraper_ultimate.py --notify   # also email watchlist matches

Output: output/showings_YYYYMMDD.json and output/latest.json (what web_app.py serves).
"""

import datetime
import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

import primecineplex
import tengis
import tix
import urgoo
import watchlist
from common import OUTPUT_DIR
from merge import merge_movies

SCRAPERS = {
    "Urgoo": urgoo.scrape,
    "Tengis": tengis.scrape,
    "Prime Cineplex": primecineplex.scrape,
    "Skywing": tix.scrape_skywing,
    "CinemaNext": tix.scrape_cinemanext,
}
LATEST_FILE = os.path.join(OUTPUT_DIR, "latest.json")


def _run_one(name, scrape):
    try:
        return name, scrape(), ""
    except Exception as e:  # one broken site must not take the others down
        traceback.print_exc()
        return name, [], f"{type(e).__name__}: {e}"


def run_scraper(parallel=True, status=None):
    """Scrape, merge and save. `status` is an optional callback(message)."""
    report = status or print
    report(f"Scraping {', '.join(SCRAPERS)}...")
    if parallel:
        with ThreadPoolExecutor(max_workers=len(SCRAPERS)) as pool:
            results = list(pool.map(lambda item: _run_one(*item), SCRAPERS.items()))
    else:
        results = [_run_one(name, scrape) for name, scrape in SCRAPERS.items()]

    records, cinemas = [], {}
    for name, movies, error in results:
        records += movies
        cinemas[name] = {"count": len(movies), "error": error}
        report(f"{name}: {len(movies)} films" + (f" (error: {error})" if error else ""))

    merged = merge_movies(records)
    payload = {
        "scraped_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.date.today().isoformat(),
        "cinemas": cinemas,
        "movies": merged,
    }
    save(payload)
    report(f"Merged {len(records)} records into {len(merged)} films")
    return payload


def save(payload):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    dated = os.path.join(OUTPUT_DIR, f"showings_{payload['date'].replace('-', '')}.json")
    for path in (dated, LATEST_FILE):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved {len(payload['movies'])} films to {dated} and {LATEST_FILE}")


def load_latest():
    """The last saved payload, or an empty one if nothing has been scraped yet."""
    if not os.path.exists(LATEST_FILE):
        return {"scraped_at": None, "date": None, "cinemas": {}, "movies": []}
    with open(LATEST_FILE, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    data = run_scraper(parallel="--sequential" not in sys.argv)
    for movie in data["movies"]:
        where = ", ".join(f"{c['name']} ×{len(c['showtimes'])}" for c in movie["cinemas"])
        print(f"- {movie['title']} | {where}")
    if "--notify" in sys.argv:
        watchlist.notify_matches(data["movies"])
