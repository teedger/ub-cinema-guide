#!/usr/bin/env python3
"""Watchlist: films the user is waiting for (files/my_movies.txt, one per line).

find_matches() compares the watchlist against merged movies; notify_matches()
emails the matches (MY_EMAIL / MY_PASSWORD env vars, Gmail SMTP; NOTIFY_TO to send
elsewhere than MY_EMAIL) and removes
them from the watchlist so the same film is not reported twice.
"""

import os
import smtplib
from email.utils import formataddr

from fuzzywuzzy import fuzz

from common import FILES_DIR
from merge import normalize_title

WATCHLIST_FILE = os.path.join(FILES_DIR, "my_movies.txt")
MATCH_THRESHOLD = 80
NOTIFY_TO = os.getenv("NOTIFY_TO") or os.getenv("MY_EMAIL", "")


def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_watchlist(names):
    os.makedirs(FILES_DIR, exist_ok=True)
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        for name in names:
            f.write(name + "\n")


def similarity(wanted, movie):
    """Best fuzzy score between a watchlist name and any title the film goes by."""
    titles = [movie.get("title", "")] + list(movie.get("titles", {}).values())
    wanted = normalize_title(wanted)
    return max((fuzz.token_set_ratio(wanted, normalize_title(t)) for t in titles if t), default=0)


def find_matches(movies, names=None, threshold=MATCH_THRESHOLD):
    names = load_watchlist() if names is None else names
    matches = []
    for wanted in names:
        best = max(movies, key=lambda m: similarity(wanted, m), default=None)
        if best is not None:
            score = similarity(wanted, best)
            if score >= threshold:
                matches.append({"watchlist_name": wanted, "movie": best, "similarity": score})
    return matches


def describe(movie):
    where = []
    for cinema in movie.get("cinemas", []):
        branches = sorted({s["branch"] for s in cinema["showtimes"] if s["branch"]})
        where.append(f"{cinema['name']} ({', '.join(branches) if branches else 'no screenings listed'})")
    return (f"{movie['title'].upper()} ({movie.get('rating') or '?'}, {movie.get('duration') or '?'}) "
            f"starts {movie.get('start_date') or '?'}. Showing at: {'; '.join(where) or 'nowhere yet'}")


def send_email(subject, body):
    my_email = os.getenv("MY_EMAIL")
    password = os.getenv("MY_PASSWORD")
    if not my_email or not password:
        print("⚠️ MY_EMAIL / MY_PASSWORD not set; skipping the email notification")
        return False
    with smtplib.SMTP("smtp.gmail.com", port=587) as connection:
        connection.starttls()
        connection.login(user=my_email, password=password)
        message = f"Subject: {subject}\n\n{body}"
        connection.sendmail(from_addr=formataddr(("🔔Notifier", my_email)), to_addrs=NOTIFY_TO,
                            msg=message.encode("utf-8"))
    print("Email has been sent successfully.")
    return True


def notify_matches(movies):
    """Email watchlist hits and drop them from the watchlist. Returns the matches."""
    names = load_watchlist()
    matches = find_matches(movies, names)
    if not matches:
        print("There are no matched movies screening in theaters today.")
        return []
    lines = [f"{i}. {describe(m['movie'])}" for i, m in enumerate(matches, 1)]
    if send_email("New Arrival(s) in cinemas", "\n\n".join(lines)):
        matched = {m["watchlist_name"] for m in matches}
        save_watchlist([n for n in names if n not in matched])
    return matches
