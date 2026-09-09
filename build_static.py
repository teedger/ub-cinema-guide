#!/usr/bin/env python3
"""Render the guide as a static site for GitHub Pages.

Reads output/latest.json (written by scraper_ultimate.py) and writes:
    site/index.html        the guide with the data embedded
    site/data/latest.json  the same data for anyone who wants it raw
    site/.nojekyll         so Pages serves the files as they are

Exits non-zero when there is nothing to publish, so a broken scrape never
replaces a good deployment.
"""

import json
import os
import shutil
import sys

from flask import render_template

import scraper_ultimate
from common import BASE_DIR
from web_app import app

SITE_DIR = os.path.join(BASE_DIR, "site")
MIN_FILMS = 1


def build():
    data = scraper_ultimate.load_latest()
    movies = data.get("movies", [])
    if len(movies) < MIN_FILMS:
        sys.exit(f"❌ Refusing to build: only {len(movies)} films in output/latest.json")

    with app.test_request_context("/"):
        html = render_template("index.html", movies=movies, meta={
            "scraped_at": data.get("scraped_at"), "date": data.get("date"), "cinemas": data.get("cinemas", {}),
        }, scraping_status=None, static_mode=True)

    shutil.rmtree(SITE_DIR, ignore_errors=True)
    os.makedirs(os.path.join(SITE_DIR, "data"))
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(SITE_DIR, "data", "latest.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    open(os.path.join(SITE_DIR, ".nojekyll"), "w").close()

    broken = [name for name, info in data.get("cinemas", {}).items() if info.get("error")]
    print(f"✅ Built {SITE_DIR} with {len(movies)} films" + (f" (cinemas with errors: {', '.join(broken)})" if broken else ""))


if __name__ == "__main__":
    build()
