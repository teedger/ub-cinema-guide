#!/usr/bin/env python3
"""Shared helpers for the cinema scrapers.

Every scraper returns a list of *movie records* in one common shape so that
merge.py can combine them regardless of which cinema they came from:

    {
        "cinema": "Urgoo",                     # Urgoo | Tengis | Prime Cineplex | Skywing
        "source_id": "HO00001936",             # the cinema's own movie id
        "title": "Hope",
        "url": "https://new.urgoo.mn/movies/HO00001936",   # movie page
        "poster": "https://...jpg",
        "description": "...",
        "genres": ["Action", "Mystery"],
        "duration": "2 цаг 37 мин",            # as shown on the site
        "duration_minutes": 157,
        "rating": "PG13",
        "start_date": "2026-09-09",
        "showtimes": [showtime(...), ...],
    }
"""

import datetime
import os
import re

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
FILES_DIR = os.path.join(BASE_DIR, "files")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")


def make_driver():
    """Headless Chrome with the same options every scraper used before."""
    options = Options()
    options.add_argument(f"user-agent={USER_AGENT}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,1000")
    if os.getenv("CI"):  # GitHub Actions runners: no sandbox user, tiny /dev/shm
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=options)


def new_movie(cinema, source_id, title, url, poster="", description="", genres=None,
              duration="", rating="", start_date=""):
    return {
        "cinema": cinema,
        "source_id": str(source_id),
        "title": clean_text(title),
        "url": url,
        "poster": poster or "",
        "description": clean_text(description),
        "genres": [clean_text(g) for g in (genres or []) if clean_text(g)],
        "duration": clean_text(duration),
        "duration_minutes": parse_duration_minutes(duration),
        "rating": clean_text(rating),
        "start_date": normalize_date(start_date),
        "showtimes": [],
    }


def showtime(date, branch, time, hall="", end_time="", fmt="", url="", available=True):
    """One screening. `url` is a direct booking link when the cinema offers one,
    otherwise the caller should pass the movie page so the site still has a link."""
    return {
        "date": normalize_date(date),
        "branch": clean_text(branch),
        "hall": clean_text(hall),
        "time": clean_text(time),
        "end_time": clean_text(end_time),
        "format": clean_text(fmt),
        "url": url or "",
        "available": bool(available),
    }


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def today_iso():
    return datetime.date.today().isoformat()


def normalize_date(value):
    """Return YYYY-MM-DD for the date formats the cinema sites use, else the raw text."""
    text = clean_text(value)
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%Y.%m.%d"):
        try:
            return datetime.datetime.strptime(text.split(" ")[0], fmt).date().isoformat()
        except ValueError:
            continue
    return text


def parse_duration_minutes(text):
    """'2 цаг 37 мин', '1 цаг 37 минут', '2H 52mins', '2 Hrs 52 mins', '92 мин' -> minutes."""
    text = clean_text(text).lower()
    if not text:
        return None
    hours = re.search(r"(\d+)\s*(цаг|h|hr|hrs|hour|hours)\b", text)
    minutes = re.search(r"(\d+)\s*(мин|минут|m|min|mins|minute|minutes)\b", text)
    if not hours and not minutes:
        return None
    return int(hours.group(1) if hours else 0) * 60 + int(minutes.group(1) if minutes else 0)


def date_from_month_day(month, day, today=None):
    """Turn a 'month/day' pair with no year (as Urgoo's date buttons show) into a
    date, assuming it is the nearest such date on or after roughly today."""
    today = today or datetime.date.today()
    year = today.year
    if month < today.month - 1:  # e.g. January buttons seen in December
        year += 1
    return datetime.date(year, month, day)
