#!/usr/bin/env python3
"""Shared helpers for the cinema scrapers.

Every scraper returns a list of *movie records* in one common shape so that
merge.py can combine them regardless of which cinema they came from:

    {
        "cinema": "Urgoo",                     # Urgoo | Tengis | Prime Cineplex | Skywing | CinemaNext
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

Films that are not showing yet use the same shape: advance sales are ordinary
showtimes on a future date, and a film that is only announced has a future
`start_date` and no showtimes.
"""

import datetime
import gzip
import http.client
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
FILES_DIR = os.path.join(BASE_DIR, "files")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

UB_TZ = datetime.timezone(datetime.timedelta(hours=8))  # Ulaanbaatar, no daylight saving
FLIGHT_CHUNK = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def fetch_html(url):
    """Download a page over plain HTTP, for the sites that render on the server."""
    # gzip matters: the pages are up to 1 MB of mostly repeated markup and the servers are far away.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "mn,en;q=0.8",
                                                   "Accept-Encoding": "gzip"})
    for attempt in (1, 2, 3):  # pages occasionally time out or arrive cut short
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body.decode("utf-8", errors="replace")
        except (OSError, http.client.HTTPException):
            if attempt == 3:
                raise
            time.sleep(attempt)


def flight_payload(html):
    """The Next.js app-router flight payload (self.__next_f.push(...)) as one string."""
    parts = []
    for chunk in FLIGHT_CHUNK.findall(html):
        try:
            item = json.loads(chunk)
        except ValueError:
            continue
        if len(item) > 1 and isinstance(item[1], str):
            parts.append(item[1])
    return "".join(parts)


def next_data(html):
    """The Next.js pages-router __NEXT_DATA__ JSON, or {} when the page has none."""
    match = NEXT_DATA.search(html)
    return json.loads(match.group(1)) if match else {}


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


def local_datetime(value):
    """'2026-09-18T14:00:00.000Z' (UTC, as the Vista-backed sites store it) -> naive
    Ulaanbaatar datetime, or None. Flight payloads prefix dates with '$D'."""
    text = clean_text(value).removeprefix("$D")
    try:
        moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UB_TZ).replace(tzinfo=None)


def duration_text(minutes):
    if not minutes:
        return ""
    hours, mins = divmod(int(minutes), 60)
    return f"{hours} цаг {mins} мин" if hours else f"{mins} мин"


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

