#!/usr/bin/env python3
"""Render the guide as a static site for GitHub Pages.

Reads output/latest.json (written by scraper_ultimate.py) and writes:
    site/index.html          the guide with the data embedded
    site/film/<id>.html      one detail page per film (shareable, with og: tags)
    site/404.html            served for missing paths, e.g. old links to films no longer showing
    site/data/latest.json    the same data for anyone who wants it raw
    site/.nojekyll           so Pages serves the files as they are
    site/CNAME               keeps the custom domain across artifact deploys
    site/static/             favicons, web manifest and the Open Graph card
    site/robots.txt, sitemap.xml, llms.txt   for search engines and AI crawlers

Exits non-zero when there is nothing to publish, so a broken scrape never
replaces a good deployment.
"""

import json
import os
import shutil
import sys

from flask import render_template

import scraper_ultimate
import seo
from common import BASE_DIR
from web_app import app, upcoming_films

SITE_DIR = os.path.join(BASE_DIR, "site")
CUSTOM_DOMAIN = "ubcinema.info"
SITE_URL = seo.SITE_URL
MIN_FILMS = 1


def build():
    data = scraper_ultimate.load_latest()
    movies = data.get("movies", [])
    if len(movies) < MIN_FILMS:
        sys.exit(f"❌ Refusing to build: only {len(movies)} films in output/latest.json")

    meta = {"scraped_at": data.get("scraped_at"), "date": data.get("date"), "cinemas": data.get("cinemas", {})}
    shutil.rmtree(SITE_DIR, ignore_errors=True)
    os.makedirs(os.path.join(SITE_DIR, "data"))
    os.makedirs(os.path.join(SITE_DIR, "film"))

    upcoming = upcoming_films(data)
    with app.test_request_context("/"):
        home = render_template("index.html", movies=movies, meta=meta, upcoming=upcoming, scraping_status=None, static_mode=True,
                               home_href="./", data_href="data/latest.json", film_href="film/{id}.html",
                               site_url=SITE_URL, canonical_url=f"{SITE_URL}/", jsonld=seo.home_jsonld(movies, SITE_URL, upcoming))
        with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
            f.write(home)
        for movie in movies:
            page_url = seo.film_url(movie["id"], SITE_URL)
            page = render_template("film.html", film=movie, movies=movies, meta=meta, upcoming=upcoming, static_mode=True,
                                   home_href="../", data_href="../data/latest.json", film_href="{id}.html",
                                   site_url=SITE_URL, canonical_url=page_url,
                                   jsonld=seo.movie_jsonld(movie, page_url, SITE_URL, today=meta["date"]))
            with open(os.path.join(SITE_DIR, "film", f"{movie['id']}.html"), "w", encoding="utf-8") as f:
                f.write(page)
        # GitHub Pages serves this for any missing path, e.g. a shared link to a film that has left cinemas.
        lost = render_template("404.html", movies=movies, meta=meta, upcoming=upcoming, static_mode=True,
                               home_href="/", data_href="/data/latest.json", film_href="/film/{id}.html", site_url=SITE_URL)
        with open(os.path.join(SITE_DIR, "404.html"), "w", encoding="utf-8") as f:
            f.write(lost)
    with open(os.path.join(SITE_DIR, "data", "latest.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    open(os.path.join(SITE_DIR, ".nojekyll"), "w").close()
    with open(os.path.join(SITE_DIR, "CNAME"), "w") as f:
        f.write(CUSTOM_DOMAIN + "\n")
    shutil.copytree(os.path.join(BASE_DIR, "static"), os.path.join(SITE_DIR, "static"))
    seo.write_crawler_files(SITE_DIR, movies, data, SITE_URL, upcoming)

    broken = [name for name, info in data.get("cinemas", {}).items() if info.get("error")]
    print(f"✅ Built {SITE_DIR} with {len(movies)} films ({len(upcoming)} coming soon) and {len(movies)} detail pages" + (f" (cinemas with errors: {', '.join(broken)})" if broken else ""))


if __name__ == "__main__":
    build()
