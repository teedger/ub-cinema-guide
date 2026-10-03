#!/usr/bin/env python3
"""Combine movie records from several cinemas into one entry per film.

Matching is done on a *normalized* title: lower-cased, punctuation removed,
Latin look-alike letters inside Mongolian words turned Cyrillic ("Сайxан") and
format/marketing tokens (IMAX, 3D, 4DX, МУСК ...) dropped. A bilingual title
("Reawaken Man: The Red - Дахин Амилсан Эр") is also matched on each half.

Two records are the same film when any of these holds:
  - their titles are equal, or share a meaningful token and fuzz.token_set_ratio
    is high;
  - they link the same YouTube trailer;
  - they have the same synopsis (the distributor's text, which cinemas copy and
    which also links an English title to a Mongolian one);
  - they open on the same day, run within a few minutes of each other and their
    titles are loosely alike ("Reawakened Man" / "Reawaken Man: The Red").
Matches are transitive, so one cinema's bilingual title joins another's English
title with a third's Mongolian one. Manual overrides live in
files/title_aliases.json ({"Тосгон МУСК": "Тосгон"}) for anything left over.
"""

import json
import os
import re
import unicodedata

from fuzzywuzzy import fuzz

import categories
from common import FILES_DIR, clean_text

ALIASES_FILE = os.path.join(FILES_DIR, "title_aliases.json")

# Tokens that describe the screening format, not the film.
FORMAT_TOKENS = {"imax", "2d", "3d", "4dx", "vip", "laser", "dolby", "atmos", "муск", "mn", "eng"}
FORMAT_LABELS = {"imax": "IMAX", "3d": "3D", "4dx": "4DX"}

CINEMA_PRIORITY = ["Urgoo", "Tengis", "Prime Cineplex", "Skywing", "CinemaNext"]
MATCH_THRESHOLD = 90
# Looser title match (fuzz.token_sort_ratio, which unlike token_set_ratio doesn't
# score "Heart of the Beast" high against "Shaun the Sheep: The Beast of ..."),
# accepted only for films that open on the same day and run within
# RUNTIME_TOLERANCE minutes of each other.
LOOSE_MATCH_THRESHOLD = 75
RUNTIME_TOLERANCE = 3
# Synopses are compared on their opening; one site may cut the text short.
SYNOPSIS_PREFIX = 150
SYNOPSIS_MIN_LENGTH = 60
SYNOPSIS_THRESHOLD = 90

# Latin letters typed in place of the Cyrillic letters they look like (lower case,
# since titles are lower-cased first): Tengis writes "Сайxан", "Үхлийн Tойрог".
# Y is left alone: in Mongolian it could stand for У or Ү.
LATIN_LOOKALIKES = str.maketrans("abcehkmoptx", "авсенкмортх")
LATIN_LOOKALIKES_UPPER = str.maketrans("ABCEHKMOPTX", "АВСЕНКМОРТХ")
CYRILLIC = re.compile(r"[\u0400-\u04ff]")
LATIN = re.compile(r"[a-zA-Z]")
# " - ", " / " or " | " between an English and a Mongolian title.
BILINGUAL_SEPARATOR = re.compile(r"\s+[-–—/|]\s+")


def load_aliases():
    if not os.path.exists(ALIASES_FILE):
        return {}
    with open(ALIASES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {normalize_title(k): v for k, v in data.items()}


def fix_lookalikes(text):
    """'Алдааны Сайxан UBIFF' -> 'Алдааны Сайхан UBIFF': Latin letters inside a word
    that also has Cyrillic letters are typos for their Cyrillic twins."""
    def fix(match):
        word = match.group(0)
        if not CYRILLIC.search(word):
            return word
        return word.translate(LATIN_LOOKALIKES_UPPER).translate(LATIN_LOOKALIKES)
    return re.sub(r"\w+", fix, text)


def tokens(title, fix_typos=True):
    text = unicodedata.normalize("NFKC", clean_text(title))
    text = (fix_lookalikes(text) if fix_typos else text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if t]


def script(text):
    """'latin', 'cyrillic' or '' (no letters, or a mix) for a piece of a title."""
    latin, cyrillic = bool(LATIN.search(text)), bool(CYRILLIC.search(text))
    return "latin" if latin and not cyrillic else "cyrillic" if cyrillic and not latin else ""


def title_variants(title):
    """The title, plus each half of an English/Mongolian bilingual title:
    'Reawaken Man: The Red - Дахин Амилсан Эр' -> [whole, 'Reawaken Man: The Red', 'Дахин Амилсан Эр'].
    A prefix in the same script ('ХКӨ - Фиорд') is not split off: it is part of the title."""
    text = fix_lookalikes(clean_text(title))
    parts = BILINGUAL_SEPARATOR.split(text)
    if len(parts) == 2 and {script(parts[0]), script(parts[1])} == {"latin", "cyrillic"}:
        return [text] + parts
    return [text]


def normalize_title(title, fix_typos=True):
    """Lower-cased title without punctuation or format tokens."""
    return " ".join(t for t in tokens(title, fix_typos) if t not in FORMAT_TOKENS)


def format_from_title(title):
    """'The Odyssey IMAX' -> 'IMAX'; 'Hope' -> ''."""
    found = [FORMAT_LABELS[t] for t in tokens(title) if t in FORMAT_LABELS]
    return " ".join(dict.fromkeys(found))


def display_title(title):
    """Title with format tokens removed, keeping the original casing/punctuation."""
    words = [w for w in fix_lookalikes(clean_text(title)).split(" ") if w.lower().strip(":()[]") not in FORMAT_TOKENS]
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


def match_keys(title, aliases):
    """Alias-aware normalized forms of the title and of each half of a bilingual title."""
    keys = []
    for variant in title_variants(title):
        n = normalize_title(variant)
        key = normalize_title(aliases.get(n, n))
        if key and key not in keys:
            keys.append(key)
    return keys


def slugify(text, fix_typos=True):
    slug = re.sub(r"[^\w]+", "-", normalize_title(text, fix_typos)).strip("-")
    return slug or "movie"


def title_slugs(title):
    """Every id a page for this title may have had: from the title as is, and from the
    title before Latin look-alike letters were fixed ('алдааны-сайxан-ubiff')."""
    return {slugify(title), slugify(title, fix_typos=False)}


def synopsis_key(movie):
    """The opening of the synopsis, normalized, or '' when it is too short to tell films apart."""
    text = " ".join(tokens(movie.get("description") or ""))
    return text[:SYNOPSIS_PREFIX] if len(text) >= SYNOPSIS_MIN_LENGTH else ""


def shared_values(movies, aliases, value):
    """Values of value(record) one cinema uses for several different films (a festival
    blurb as synopsis, a promo reel as trailer), which say nothing about which film a
    record is."""
    seen, shared = {}, set()
    for m in movies:
        key = value(m)
        if not key:
            continue
        film = tuple(match_keys(m["title"], aliases)[:1])
        if seen.setdefault((m["cinema"], key), film) != film:
            shared.add(key)
    return shared


def same_opening(a, b):
    """Both open on the same day and run within RUNTIME_TOLERANCE minutes of each other."""
    da, db = a.get("duration_minutes"), b.get("duration_minutes")
    return (bool(a.get("start_date")) and a.get("start_date") == b.get("start_date")
            and bool(da) and bool(db) and abs(da - db) <= RUNTIME_TOLERANCE)


def records_match(a, b, boilerplate=frozenset()):
    """Whether two prepared records (see cluster_movies) are the same film. Synopses
    and trailers in `boilerplate` don't count."""
    if any(ka == kb or titles_match(ka, kb) for ka in a["_keys"] for kb in b["_keys"]):
        return True
    if a.get("trailer") and a.get("trailer") == b.get("trailer") and a["trailer"] not in boilerplate:
        return True
    sa, sb = a["_synopsis"], b["_synopsis"]
    if sa and sb and sa not in boilerplate and sb not in boilerplate:
        # Compare equal lengths so a synopsis cut short still matches the full one.
        n = min(len(sa), len(sb))
        if fuzz.ratio(sa[:n], sb[:n]) >= SYNOPSIS_THRESHOLD:
            return True
    if same_opening(a, b):
        return any(script(ka) == script(kb) != "" and fuzz.token_sort_ratio(ka, kb) >= LOOSE_MATCH_THRESHOLD
                   for ka in a["_keys"] for kb in b["_keys"])
    return False


def cluster_movies(movies, aliases=None):
    """Group movie records that are the same film. Returns a list of lists, each in
    cinema priority order. Every pair of records is compared and matches are joined
    transitively, so the result doesn't depend on which cinema is read first."""
    aliases = aliases if aliases is not None else load_aliases()
    ordered = sorted(movies, key=lambda m: (
        CINEMA_PRIORITY.index(m["cinema"]) if m["cinema"] in CINEMA_PRIORITY else 99,
        -len(m.get("title", "")),
    ))
    records = [{**m, "_keys": match_keys(m["title"], aliases), "_synopsis": synopsis_key(m)} for m in ordered]
    boilerplate = (shared_values(ordered, aliases, synopsis_key)
                   | shared_values(ordered, aliases, lambda m: m.get("trailer")))

    parent = list(range(len(records)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if root(i) != root(j) and records_match(records[i], records[j], boilerplate):
                parent[max(root(i), root(j))] = min(root(i), root(j))

    clusters = {}
    for i, movie in enumerate(ordered):
        clusters.setdefault(root(i), []).append(movie)
    return list(clusters.values())


def first_nonempty(cluster, field):
    for m in cluster:
        if m.get(field):
            return m[field]
    return ""


def standard_genres(cluster):
    """Every cinema's genres for the film in the shared vocabulary, first-mentioned first."""
    genres = []
    for m in cluster:
        for name in m.get("genres") or []:
            genre = categories.standard_genre(name)
            if not genre:
                print(f"⚠️ Unknown genre {name!r} from {m['cinema']} ({m['title']}): add it to categories.py")
            elif genre not in genres:
                genres.append(genre)
    return genres


def standard_rating(cluster):
    """The strictest rating any of the film's cinemas gives it, as G / PG / PG-13 / R."""
    ratings = []
    for m in cluster:
        if m.get("rating"):
            rating = categories.standard_rating(m["rating"])
            if not rating:
                print(f"⚠️ Unknown rating {m['rating']!r} from {m['cinema']} ({m['title']}): add it to categories.py")
            ratings.append(rating)
    return categories.strictest(ratings)


def merge_cluster(cluster):
    """Build one website entry from all records of the same film."""
    title = max((display_title(m["title"]) for m in cluster), key=len)
    cinemas = {}
    for m in cluster:
        entry = cinemas.setdefault(m["cinema"], {
            "name": m["cinema"], "url": m["url"], "title": m["title"], "start_date": m.get("start_date", ""),
            "showtimes": [],
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
        # Ids this film's page went by while some cinema's title was a film of its own,
        # e.g. 'reawakened-man'; merge_movies keeps the ones no other film uses.
        "aliases": sorted(set().union(*(title_slugs(m["title"]) for m in cluster))),
        "title": title,
        "titles": {m["cinema"]: m["title"] for m in cluster},
        "description": max(descriptions, key=len) if descriptions else "",
        "genres": standard_genres(cluster),
        "duration": first_nonempty(cluster, "duration"),
        "duration_minutes": first_nonempty(cluster, "duration_minutes") or None,
        "rating": standard_rating(cluster),
        "start_date": start_dates[0] if start_dates else "",
        "poster": first_nonempty(cluster, "poster"),
        "trailer": first_nonempty(cluster, "trailer"),
        "cinemas": [cinemas[c] for c in CINEMA_PRIORITY if c in cinemas]
                   + [v for k, v in cinemas.items() if k not in CINEMA_PRIORITY],
        "dates": sorted({s["date"] for s in all_shows if s["date"]}),
        "showtime_count": len(all_shows),
    }


def upcoming_date(movie, today):
    """The day a film that is not showing yet arrives: its first advance screening or
    its announced opening, whichever is sooner. '' when it is already showing.
    templates/base.html has the same rule in JavaScript (upcomingDate)."""
    start, dates = movie.get("start_date") or "", movie.get("dates") or []
    if (start and start <= today) or any(d <= today for d in dates):
        return ""
    return min([d for d in (start, *dates[:1]) if d], default="")


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
    # An alias only redirects when it is unambiguous: not a current film's id and
    # not claimed by two films.
    ids = {m["id"] for m in merged}
    claims = {}
    for m in merged:
        for alias in m["aliases"]:
            claims[alias] = claims.get(alias, 0) + 1
    for m in merged:
        m["aliases"] = [a for a in m["aliases"] if a not in ids and claims[a] == 1]
    return merged
