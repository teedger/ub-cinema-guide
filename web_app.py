#!/usr/bin/env python3
"""Cinema guide web app: one page listing every film showing in Ulaanbaatar's
cinemas (Urgoo, Tengis, Prime Cineplex, Skywing) with screens, times and booking links.

Data comes from output/latest.json, written by scraper_ultimate.py. The
"Refresh" button runs the scrapers in a background thread.
"""

import os
from threading import Thread

from flask import Flask, abort, jsonify, render_template, request

import scraper_ultimate
import seo
import watchlist

app = Flask(__name__)
app.secret_key = os.urandom(24)

scraping_status = {"is_scraping": False, "last_scrape": None, "message": "", "movies_count": 0}


def load_data():
    return scraper_ultimate.load_latest()


def run_scraper():
    scraping_status["is_scraping"] = True
    scraping_status["message"] = "Starting scrapers..."

    def status(message):
        scraping_status["message"] = message

    try:
        payload = scraper_ultimate.run_scraper(status=status)
        scraping_status["last_scrape"] = payload["scraped_at"]
        scraping_status["movies_count"] = len(payload["movies"])
        scraping_status["message"] = f"Found {len(payload['movies'])} films"
        try:
            watchlist.notify_matches(payload["movies"])
        except Exception as e:
            print(f"⚠️ Watchlist notification failed: {e}")
    except Exception as e:
        scraping_status["message"] = f"Error: {e}"
    finally:
        scraping_status["is_scraping"] = False


def page_context(data):
    """Variables every page needs; the static build overrides the hrefs."""
    return {
        "meta": {"scraped_at": data.get("scraped_at"), "date": data.get("date"), "cinemas": data.get("cinemas", {})},
        "home_href": "/", "data_href": "/api/movies", "film_href": "/film/{id}", "static_mode": False,
        "site_url": seo.SITE_URL,
    }


@app.route("/")
def index():
    data = load_data()
    return render_template("index.html", movies=data["movies"], scraping_status=scraping_status,
                           jsonld=seo.home_jsonld(data["movies"]), **page_context(data))


@app.route("/film/<film_id>")
def film(film_id):
    data = load_data()
    movie = next((m for m in data["movies"] if m["id"] == film_id), None)
    if movie is None:
        abort(404)
    return render_template("film.html", film=movie, movies=data["movies"],
                           jsonld=seo.movie_jsonld(movie, seo.film_url(film_id), today=data.get("date")), **page_context(data))


@app.route("/api/movies")
def api_movies():
    return jsonify(load_data())


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    if scraping_status["is_scraping"]:
        return jsonify({"status": "error", "message": "Already scraping!"}), 429
    Thread(target=run_scraper, daemon=True).start()
    return jsonify({"status": "started", "message": "Scraping started!"})


@app.route("/api/scrape/status")
def api_scrape_status():
    return jsonify(scraping_status)


@app.route("/watchlist")
def watchlist_page():
    data = load_data()
    movies = data["movies"]
    names = watchlist.load_watchlist()
    return render_template("watchlist.html", watchlist=names, matches=watchlist.find_matches(movies, names),
                           currently_showing=movies, **page_context(data))


@app.route("/api/watchlist", methods=["GET", "POST", "DELETE"])
def api_watchlist():
    names = watchlist.load_watchlist()
    if request.method == "GET":
        return jsonify(names)
    movie = (request.json or {}).get("movie", "").strip()
    if not movie:
        return jsonify({"error": "Movie name required"}), 400
    if request.method == "POST":
        if movie in names:
            return jsonify({"status": "exists", "watchlist": names})
        names.append(movie)
        watchlist.save_watchlist(names)
        return jsonify({"status": "added", "watchlist": names})
    if movie not in names:
        return jsonify({"error": "Movie not found"}), 404
    names.remove(movie)
    watchlist.save_watchlist(names)
    return jsonify({"status": "removed", "watchlist": names})


@app.route("/api/watchlist/check")
def api_watchlist_check():
    return jsonify(watchlist.find_matches(load_data()["movies"]))


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
