"""One genre and age-rating vocabulary for all five cinemas.

Urgoo and Prime Cineplex name genres in English, Tengis and tix.mn (Skywing,
CinemaNext) in Mongolian with their own spellings; ratings come as 'PG13',
'PG-13', 'PG13 13+', '12+', 'G 0+', 'Бүх нас'... merge.py maps every film onto
the lists below so the site can filter by them. A value that maps to nothing
is reported, so a new spelling can be added here.
"""

import re

# Display order in the genre filter.
GENRES = ["Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family",
          "Fantasy", "History", "Horror", "Music", "Mystery", "Romance", "Science Fiction", "Thriller", "War"]

# Lower-case cinema spelling -> standard genre. English names map to themselves (added below).
GENRE_ALIASES = {
    "тулаант": "Action",
    "адал явдал": "Adventure",
    "анимейшин": "Animation", "хүүхэлдэйн": "Animation", "anime": "Animation", "аниме": "Animation",
    "инээдэм": "Comedy", "инээдмийн": "Comedy",
    "гэмт хэрэг": "Crime",
    "баримтат": "Documentary",
    "драм": "Drama", "драма": "Drama",
    "гэр бүл": "Family", "гэр бүлийн": "Family",
    "уран зөгнөл": "Fantasy",
    "түүхэн": "History",
    "аймшиг": "Horror", "аймшгийн": "Horror", "аймшигийн": "Horror",
    "хөгжмийн": "Music", "хөгжим": "Music", "musical": "Music",
    "битүүлэг": "Mystery",
    "дурлалт": "Romance", "романс": "Romance", "романтик": "Romance",
    "шинжлэх ухаан": "Science Fiction", "шинжлэх ухааны уран зөгнөл": "Science Fiction", "sci-fi": "Science Fiction",
    "түгшүүрт": "Thriller",
    "дайн": "War", "дайны": "War",
}
GENRE_ALIASES.update({g.lower(): g for g in GENRES})

# Mildest first; a film's rating is the strictest any of its cinemas gives it.
RATINGS = ["G", "PG", "PG-13", "R"]


def _key(text):
    # Tengis sometimes types a Latin x for the Cyrillic х ('Xүүxэлдэйн').
    text = (text or "").strip().lower().replace("x", "х")
    return re.sub(r"\s+", " ", text)


def standard_genre(name):
    """'Инээдмийн' -> 'Comedy'; None when the spelling is unknown."""
    key = _key(name)
    # The Latin-x fix must not break English names that contain an x.
    return GENRE_ALIASES.get(key) or GENRE_ALIASES.get((name or "").strip().lower())


def standard_rating(text):
    """'PG13 13+', '12+', 'R 18+', 'Бүх нас' ... -> 'G' | 'PG' | 'PG-13' | 'R'; '' when unknown."""
    t = (text or "").strip().upper().replace(" ", "")
    if not t:
        return ""
    if t.startswith(("PG-13", "PG13")) or re.fullmatch(r"1[2-5]\+", t):
        return "PG-13"
    if t.startswith(("R", "NC-17", "NC17")) or re.fullmatch(r"1[6-8]\+", t):
        return "R"
    if t.startswith("PG") or re.fullmatch(r"[6-9]\+", t):
        return "PG"
    if t.startswith("G") or t in ("0+", "БҮХНАС"):
        return "G"
    return ""


def strictest(ratings):
    known = [r for r in ratings if r in RATINGS]
    return max(known, key=RATINGS.index) if known else ""
