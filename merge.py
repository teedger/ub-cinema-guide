#!/usr/bin/env python3
"""Combine movie records from several cinemas into one entry per film.

Matching is done on a *normalized* title: lower-cased, punctuation removed and
format/marketing tokens (IMAX, 3D, 4DX, МУСК ...) dropped. Two titles are the
same film when the normalized forms are equal, or when they share a meaningful
token and fuzz.token_set_ratio is high. Manual overrides live in
files/title_aliases.json ({"Тосгон МУСК": "Тосгон"}) for the cases fuzzy
matching can't see, e.g. a Mongolian title on one site and English on another.
"""

import json
import os
import re
import unicodedata

from fuzzywuzzy import fuzz

from common import FILES_DIR, clean_text

ALIASES_FILE = os.path.join(FILES_DIR, "title_aliases.json")

# Tokens that describe the screening format, not the film.
FORMAT_TOKENS = {"imax", "2d", "3d", "4dx", "vip", "laser", "dolby", "atmos", "муск", "mn", "eng"}
FORMAT_LABELS = {"imax": "IMAX", "3d": "3D", "4dx": "4DX"}

CINEMA_PRIORITY = ["Urgoo", "Tengis", "Prime Cineplex", "Skywing"]
MATCH_THRESHOLD = 90


def load_aliases():
    if not os.path.exists(ALIASES_FILE):
        return {}
    with open(ALIASES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {normalize_title(k): v for k, v in data.items()}


def tokens(title):
    text = unicodedata.normalize("NFKC", clean_text(title)).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if t]


def normalize_title(title):
    """Lower-cased title without punctuation or format tokens."""
    return " ".join(t for t in tokens(title) if t not in FORMAT_TOKENS)


def format_from_title(title):
    """'The Odyssey IMAX' -> 'IMAX'; 'Hope' -> ''."""
    found = [FORMAT_LABELS[t] for t in tokens(title) if t in FORMAT_LABELS]
    return " ".join(dict.fromkeys(found))


def display_title(title):
    """Title with format tokens removed, keeping the original casing/punctuation."""
    words = [w for w in clean_text(title).split(" ") if w.lower().strip(":()[]") not in FORMAT_TOKENS]
    return re.sub(r"\s+", " ", " ".join(words)).strip(" :-–")


def titles_match(a, b):
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shared = set(na.split()) & set(nb.split())
    # Don't merge two films that only share a tiny token such as "2" or "the".
    if not shared or len("".join(shared)) < 4:
        return False
    return fuzz.token_set_ratio(na, nb) >= MATCH_THRESHOLD


def match_key(title, aliases):
    """Alias-aware normalized title used for clustering."""
    n = normalize_title(title)
    return normalize_title(aliases.get(n, n))


def slugify(text):
    slug = re.sub(r"[^\w]+", "-", normalize_title(text)).strip("-")
    return slug or "movie"


def cluster_movies(movies, aliases=None):
    """Group movie records that are the same film. Returns a list of lists."""
    aliases = aliases if aliases is not None else load_aliases()
    ordered = sorted(movies, key=lambda m: (
        CINEMA_PRIORITY.index(m["cinema"]) if m["cinema"] in CINEMA_PRIORITY else 99,
        -len(m.get("title", "")),
    ))
    clusters = []
    for movie in ordered:
        key = match_key(movie["title"], aliases)
        target = None
        for cluster in clusters:
            if any(key == c["_key"] or titles_match(key, c["_key"]) for c in cluster):
                target = cluster
                break
        if target is None:
            target = []
            clusters.append(target)
        target.append({**movie, "_key": key})
    return [[{k: v for k, v in m.items() if k != "_key"} for m in cluster] for cluster in clusters]


def first_nonempty(cluster, field):
    for m in cluster:
        if m.get(field):
            return m[field]
    return "" if field not in ("genres",) else []


def merge_cluster(cluster):
    """Build one website entry from all records of the same film."""
    title = max((display_title(m["title"]) for m in cluster), key=len)
    cinemas = {}
    for m in cluster:
        entry = cinemas.setdefault(m["cinema"], {
            "name": m["cinema"], "url": m["url"], "title": m["title"], "showtimes": [],
        })
        fmt = format_from_title(m["title"])
        for s in m["showtimes"]:
            s = dict(s)
            if fmt and not s.get("format"):
                s["format"] = fmt
            if not s.get("url"):
                s["url"] = m["url"]
            entry["showtimes"].append(s)
    for entry in cinemas.values():
        seen = set()
        unique = []
        for s in sorted(entry["showtimes"], key=lambda s: (s["date"], s["branch"], s["time"])):
            k = (s["date"], s["branch"], s["hall"], s["time"], s["format"])
            if k not in seen:
                seen.add(k)
                unique.append(s)
        entry["showtimes"] = unique

    all_shows = [s for c in cinemas.values() for s in c["showtimes"]]
    start_dates = sorted(m["start_date"] for m in cluster if m.get("start_date"))
    descriptions = [m["description"] for m in cluster if m.get("description")]
    return {
        "id": slugify(title),
        "title": title,
        "titles": {m["cinema"]: m["title"] for m in cluster},
        "description": max(descriptions, key=len) if descriptions else "",
        "genres": first_nonempty(cluster, "genres"),
        "duration": first_nonempty(cluster, "duration"),
        "duration_minutes": first_nonempty(cluster, "duration_minutes") or None,
        "rating": first_nonempty(cluster, "rating"),
        "start_date": start_dates[0] if start_dates else "",
        "poster": first_nonempty(cluster, "poster"),
        "cinemas": [cinemas[c] for c in CINEMA_PRIORITY if c in cinemas]
                   + [v for k, v in cinemas.items() if k not in CINEMA_PRIORITY],
        "dates": sorted({s["date"] for s in all_shows if s["date"]}),
        "showtime_count": len(all_shows),
    }


def merge_movies(movies, aliases=None):
    merged = [merge_cluster(c) for c in cluster_movies(movies, aliases)]
    # Films with screenings first, then by title.
    merged.sort(key=lambda m: (m["showtime_count"] == 0, m["title"].lower()))
    # Make ids unique in case two different films normalize to the same slug.
    seen = {}
    for m in merged:
        n = seen.get(m["id"], 0)
        seen[m["id"]] = n + 1
        if n:
            m["id"] = f"{m['id']}-{n + 1}"
    return merged
