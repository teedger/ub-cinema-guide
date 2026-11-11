"""One genre and age-rating vocabulary for all five cinemas.

Urgoo and Prime Cineplex name genres in English, Tengis and tix.mn (Skywing,
CinemaNext) in Mongolian with their own spellings, and any of them may invent a
new one ('Superhero superbaatar', 'Уянгын'); ratings come as 'PG13',
'PG-13', 'PG13 13+', '12+', 'G 0+', 'Бүх нас'... merge.py maps every film onto
the lists below so the site can filter by them. A value that maps to nothing
is reported, so a new spelling can be added here.
"""

import re

# Display order in the genre filter.
GENRES = ["Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family",
          "Fantasy", "History", "Horror", "Music", "Mystery", "Romance", "Science Fiction", "Thriller", "War"]

# Lower-case cinema spelling -> standard genre. English names map to themselves (added below).
# The cinemas type genres by hand, so the same genre turns up as a stem, an adjective form
# ('аймшиг', 'аймшгийн', 'аймшигт'), a loanword ('хоррор'), English or Latin-script Mongolian.
# Genres outside GENRES go to the closest one: biography and sport -> Drama, superhero -> Action.
_ALIASES = {
    "Action": [
        "тулаант", "тулаан", "тулааны", "тулаант кино", "экшн", "экшен", "экшэн", "акшн", "action", "action film",
        "супер баатар", "супербаатар", "супер баатрын", "супербаатрын", "баатарлаг", "superhero", "super hero",
        "super-hero", "superbaatar", "super baatar", "tulaant", "tulaan",
        "тулааны урлаг", "кунг фу", "кунг-фу", "martial arts", "kung fu", "каратэ",
        "уралдаан", "уралдааны", "хурдан", "racing", "гамшиг", "гамшгийн", "disaster", "буудлага", "shooter",
    ],
    "Adventure": [
        "адал явдал", "адал явдалт", "адал явдлын", "адал", "adal yavdal", "аялал", "аяллын", "adventure",
        "вестерн", "western", "ковбой", "cowboy",
    ],
    "Animation": [
        "хүүхэлдэйн", "хүүхэлдэйн кино", "хүүхэлдэй", "huuhelden", "хvvхэлдэйн", "анимейшин", "анимейшн", "анимэйшн",
        "анимэйшин", "анимац", "анимацийн", "анимэ", "аниме", "anime", "мульт", "мультфильм", "мультик",
        "animation", "animated", "cartoon", "3d animation", "2d animation",
    ],
    "Comedy": [
        "инээдэм", "инээдмийн", "инээдэмтэй", "инээдтэй", "инээд", "ineedem", "ineedmiin", "хошин", "хошин шог",
        "хошигнол", "комеди", "комедийн", "comedy", "comedies", "parody", "пародия", "sitcom", "romcom", "rom-com",
    ],
    "Crime": [
        "гэмт хэрэг", "гэмт хэргийн", "гэмт", "криминал", "криминалын", "crime", "gangster", "гангстер", "мафи",
        "мафийн", "mafia", "heist", "дээрэм", "дээрмийн", "дээрэмчин", "дээрэмчид", "хулгай", "хулгайч",
    ],
    "Documentary": [
        "баримтат", "баримтат кино", "баримтын", "barimtat", "документ", "документал", "документар",
        "documentary", "docu", "doc",
    ],
    "Drama": [
        "драм", "драма", "драмын", "жүжиг", "жүжгийн", "амьдралын", "уянгын", "уянга", "уянгалаг", "мелодрам",
        "мелодрама", "melodrama", "drama", "dramas", "намтар", "намтарчилсан", "намтрын", "biography",
        "biographical", "biopic", "спорт", "спортын", "sport", "sports", "нийгмийн", "social", "бодит явдал",
        "бодит явдлаас сэдэвлэсэн", "бодит түүх", "true story", "based on a true story", "coming of age",
    ],
    "Family": [
        "гэр бүл", "гэр бүлийн", "гэр бvл", "ger bul", "ger buliin", "хүүхдийн", "хүүхэд", "хүүхдэд",
        "хүүхэд залуучуудын", "бүх насны", "family", "kids", "children", "children's",
    ],
    "Fantasy": [
        "уран зөгнөл", "уран зөгнөлт", "уран зөгнөлийн", "уран зөгнөлтэй", "уран зөгнөлт кино", "uran zugnul",
        "фэнтези", "фэнтэзи", "фентези", "фэнтази", "fantasy", "ид шид", "ид шидийн", "шидэт", "шидтэн", "магик",
        "magic", "үлгэр", "үлгэрийн", "домог", "домгийн", "домогт", "ер бусын", "ер бусын үзэгдэл", "supernatural",
        "мистик", "mystic", "mythology", "fairy tale",
    ],
    "History": [
        "түүхэн", "түүх", "түүхийн", "tuuhen", "history", "historical", "эпик", "epic", "period", "period drama",
    ],
    "Horror": [
        "аймшиг", "аймшгийн", "аймшигийн", "аймшигт", "аймшигтай", "аймшгийн кино", "aimshig", "aimshgiin",
        "айдас", "айдсын", "хорор", "хоррор", "horror", "slasher", "зомби", "zombie", "сүнс", "сүнсний",
        "чөтгөр", "чөтгөрийн", "вампир", "vampire", "ghost",
    ],
    "Music": [
        "хөгжмийн", "хөгжим", "хөгжимт", "мюзикл", "мюзикал", "musical", "music", "концерт", "concert",
        "бүжиг", "бүжгийн", "dance",
    ],
    "Mystery": [
        "битүүлэг", "битүүлгийн", "битүүлэгтэй", "bituuleg", "нууцлаг", "нууц", "нууцын", "mystery", "детектив",
        "detective", "мөрдөгч", "мөрдөгчийн", "мөрдөн байцаалт", "мөрдлөг", "мөрдлөгө", "whodunit",
    ],
    "Romance": [
        "дурлал", "дурлалт", "дурлалын", "durlal", "durlalt", "хайр", "хайрын", "хайр дурлал", "хайр дурлалын",
        "романс", "романтик", "романтик кино", "romance", "romantic", "love", "love story",
    ],
    "Science Fiction": [
        "шинжлэх ухаан", "шинжлэх ухааны", "шинжлэх ухаант", "шинжлэх ухааны уран зөгнөл",
        "шинжлэх ухааны уран зөгнөлт", "шинжлэх ухаант уран зөгнөлт", "шинжлэх ухааны фантастик", "ш.у",
        "ш/у", "шу", "ш.у.у.з", "shinjleh uhaan", "sci-fi", "scifi", "sci fi", "sf", "science", "science fiction",
        "science-fiction", "фантастик", "фантастик кино", "сайнс фикшн", "сансар", "сансрын", "space",
        "кибер", "cyberpunk", "киберпанк", "дистопи", "dystopia", "dystopian", "робот", "robot",
    ],
    "Thriller": [
        "түгшүүрт", "түгшүүр", "түгшүүртэй", "tugshuurt", "триллер", "трилер", "thriller", "сэтгэл зүйн",
        "сэтгэлзүйн", "psychological", "suspense", "сэжиг", "сэжигтэй", "тагнуул", "тагнуулын", "spy",
        "espionage", "аюул", "аюултай",
    ],
    "War": [
        "дайн", "дайны", "дайнд", "dain", "war", "military", "цэрэг", "цэргийн", "байлдаан", "байлдааны",
    ],
}
GENRE_ALIASES = {alias: genre for genre, aliases in _ALIASES.items() for alias in aliases}
GENRE_ALIASES.update({g.lower(): g for g in GENRES})
# Aliases long enough to look for inside a longer name ('Superhero superbaatar', 'Аймшигт триллер').
# Short ones like 'sf' or 'war' would match inside unrelated words; they only count as whole words.
_LONGEST_FIRST = sorted(GENRE_ALIASES, key=len, reverse=True)

# Mildest first; a film's rating is the strictest any of its cinemas gives it.
RATINGS = ["G", "PG", "PG-13", "R"]


def _key(text):
    # Strip list debris ("['АЙМШИГ'") and punctuation around the name.
    text = re.sub(r"^[\s\[\]'\"().,;:]+|[\s\[\]'\"().,;:]+$", "", (text or "").lower())
    return re.sub(r"\s+", " ", text)


def _lookup(key):
    # Tengis sometimes types a Latin x for the Cyrillic х ('Xүүxэлдэйн'), but English names
    # contain real x's, so try the name both ways.
    return GENRE_ALIASES.get(key) or GENRE_ALIASES.get(key.replace("x", "х"))


def genres_of(name):
    """Every standard genre named in one cinema genre label, first-mentioned first.
    'Инээдмийн' -> ['Comedy']; 'Superhero superbaatar' -> ['Action'];
    'Romantic comedy' -> ['Romance', 'Comedy']; 'Аймшиг, түгшүүрт' -> ['Horror', 'Thriller']; unknown -> []."""
    key = _key(name)
    if not key:
        return []
    exact = _lookup(key)
    if exact:
        return [exact]
    found = []
    # Several genres in one label: 'Action/Comedy', 'Аймшиг, түгшүүрт', 'Драм · Дурлалт'.
    parts = [p for p in (_key(p) for p in re.split(r"[,/|;&·+]|\s-\s|\sба\s|\sand\s", key)) if p]
    for part in parts:
        genre = _lookup(part)
        if genre:
            found.append((0, genre))
            continue
        # Known words inside a longer label, longest first so 'шинжлэх ухааны уран зөгнөл'
        # counts as Science Fiction and not also as Fantasy.
        text = " " + part.replace("x", "х") + " "
        for alias in _LONGEST_FIRST:
            a = alias.replace("x", "х")
            pattern = re.escape(a) if len(a) >= 5 else r"(?<!\w)" + re.escape(a) + r"(?!\w)"
            m = re.search(pattern, text)
            if m:
                found.append((m.start(), GENRE_ALIASES[alias]))
                text = text[:m.start()] + " " * len(m.group()) + text[m.end():]
    genres = []
    for _, genre in sorted(found, key=lambda f: f[0]) if len(parts) == 1 else found:
        if genre not in genres:
            genres.append(genre)
    return genres


def standard_genre(name):
    """'Инээдмийн' -> 'Comedy'; None when the spelling is unknown. The first of genres_of."""
    genres = genres_of(name)
    return genres[0] if genres else None


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
