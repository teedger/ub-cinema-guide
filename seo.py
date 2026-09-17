"""Search and AI-crawler facing extras: structured data, sitemap, robots.txt and llms.txt.

Both the Flask app and the static build use the same JSON-LD builders so the
pages describe themselves identically wherever they are served from.
"""
import os
from datetime import date
from urllib.parse import quote

SITE_URL = "https://ubcinema.info"
SITE_NAME = "UB Cinema Guide"
SITE_DESCRIPTION = ("Today's cinema showtimes in Ulaanbaatar. Urgoo, Tengis, Prime Cineplex and Skywing "
                    "listings merged into one guide, updated every morning.")
TZ_OFFSET = "+08:00"  # Ulaanbaatar, no daylight saving

CINEMA_SITES = {"Urgoo": "https://new.urgoo.mn", "Tengis": "https://www.tengis.mn", "Prime Cineplex": "https://www.primecineplex.mn",
                "Skywing": "https://www.tix.mn/theaters/skywing"}


def film_url(movie_id, site_url=SITE_URL):
    """Absolute, percent-encoded page URL (ids can contain Cyrillic)."""
    return f"{site_url}/film/{quote(movie_id)}.html"


def locality(branch):
    """Urgoo has halls outside the capital; everything else is in Ulaanbaatar."""
    if "Эрдэнэт" in branch:
        return "Erdenet"
    if "Дархан" in branch:
        return "Darkhan"
    return "Ulaanbaatar"


def upcoming_showtimes(movie, today=None, limit=120):
    today = today or date.today().isoformat()
    out = []
    for cinema in movie.get("cinemas", []):
        for s in cinema.get("showtimes", []):
            if s.get("date", "") >= today and s.get("time"):
                out.append((cinema, s))
    out.sort(key=lambda cs: (cs[1]["date"], cs[1]["time"]))
    return out[:limit]


def movie_jsonld(movie, page_url, site_url=SITE_URL, today=None):
    """Movie + one ScreeningEvent per upcoming showtime + breadcrumb, as a schema.org graph."""
    movie_id = f"{page_url}#movie"
    m = {"@type": "Movie", "@id": movie_id, "name": movie["title"], "url": page_url}
    alt = sorted({t for t in (movie.get("titles") or {}).values() if t and t != movie["title"]})
    if alt:
        m["alternateName"] = alt
    if movie.get("poster"):
        m["image"] = movie["poster"]
    if movie.get("description"):
        m["description"] = movie["description"]
    if movie.get("genres"):
        m["genre"] = movie["genres"]
    if movie.get("duration_minutes"):
        m["duration"] = f"PT{int(movie['duration_minutes'])}M"
    if movie.get("rating"):
        m["contentRating"] = movie["rating"]

    events = []
    for cinema, s in upcoming_showtimes(movie, today):
        ev = {
            "@type": "ScreeningEvent",
            "name": f"{movie['title']} at {cinema['name']} {s.get('branch', '')}".strip(),
            "startDate": f"{s['date']}T{s['time']}:00{TZ_OFFSET}",
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "workPresented": {"@id": movie_id},
            "location": {
                "@type": "MovieTheater",
                "name": f"{cinema['name']} {s.get('branch', '')}".strip(),
                "address": {"@type": "PostalAddress", "addressLocality": locality(s.get("branch", "")), "addressCountry": "MN"},
            },
        }
        if s.get("end_time"):
            ev["endDate"] = f"{s['date']}T{s['end_time']}:00{TZ_OFFSET}"
        if s.get("format"):
            ev["videoFormat"] = s["format"]
        url = s.get("url") or cinema.get("url")
        if url:
            ev["url"] = url
            ev["offers"] = {"@type": "Offer", "url": url,
                            "availability": "https://schema.org/InStock" if s.get("available", True) else "https://schema.org/SoldOut"}
        events.append(ev)

    crumbs = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": SITE_NAME, "item": f"{site_url}/"},
        {"@type": "ListItem", "position": 2, "name": movie["title"], "item": page_url},
    ]}
    return {"@context": "https://schema.org", "@graph": [m, *events, crumbs]}


def home_jsonld(movies, site_url=SITE_URL, upcoming=None):
    """WebSite + the lists of films now showing and coming soon. `upcoming` is {film id: first day}."""
    upcoming = upcoming or {}

    def item_list(name, films):
        return {"@type": "ItemList", "name": name, "numberOfItems": len(films),
                "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": m["title"], "url": film_url(m["id"], site_url)}
                                    for i, m in enumerate(films)]}

    soon = sorted((m for m in movies if m["id"] in upcoming), key=lambda m: upcoming[m["id"]])
    return {"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "@id": f"{site_url}/#website", "name": SITE_NAME, "url": f"{site_url}/",
         "description": SITE_DESCRIPTION, "inLanguage": ["en", "mn"],
         "about": {"@type": "City", "name": "Ulaanbaatar", "sameAs": "https://www.wikidata.org/wiki/Q23430"}},
        item_list("Films now showing in Ulaanbaatar", [m for m in movies if m["id"] not in upcoming]),
        *([item_list("Films coming soon to Ulaanbaatar cinemas", soon)] if soon else []),
    ]}


def film_summary(movie, opening=""):
    bits = []
    if movie.get("genres"):
        bits.append(", ".join(movie["genres"]))
    if movie.get("duration_minutes"):
        bits.append(f"{movie['duration_minutes']} min")
    if movie.get("rating"):
        bits.append(movie["rating"])
    cinemas = ", ".join(c["name"] for c in movie.get("cinemas", []))
    if cinemas:
        bits.append(f"from {opening} at {cinemas}" + (", tickets on sale" if movie.get("showtime_count") else "")
                    if opening else f"showing at {cinemas}")
    return " · ".join(bits)


def write_crawler_files(site_dir, movies, data, site_url=SITE_URL, upcoming=None):
    """robots.txt, sitemap.xml and llms.txt next to the built pages. `upcoming` is {film id: first day}."""
    upcoming = upcoming or {}
    day = (data.get("date") or date.today().isoformat())[:10]

    with open(os.path.join(site_dir, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("# Everyone is welcome, search engines and AI assistants alike.\n"
                "User-agent: *\nAllow: /\n\n"
                f"Sitemap: {site_url}/sitemap.xml\n")

    urls = [(f"{site_url}/", "daily", "1.0")] + [(film_url(m["id"], site_url), "daily", "0.8") for m in movies]
    with open(os.path.join(site_dir, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for loc, freq, prio in urls:
            f.write(f"  <url><loc>{loc}</loc><lastmod>{day}</lastmod><changefreq>{freq}</changefreq><priority>{prio}</priority></url>\n")
        f.write("</urlset>\n")

    lines = [f"# {SITE_NAME}", "", f"> {SITE_DESCRIPTION}", "",
             "Listings are collected from the cinemas' own websites once a day at 05:00 Ulaanbaatar time (UTC+8). "
             "All times are local Ulaanbaatar time. Confirm on the cinema's site before travelling.", "",
             "## Pages", "",
             f"- [Home]({site_url}/): films and screenings, filterable by day and cinema",
             f"- [Raw data (JSON)]({site_url}/data/latest.json): every film and screening in machine-readable form",
             f"- [Sitemap]({site_url}/sitemap.xml)",
             "- [Source code](https://github.com/teedger/ub-cinema-guide)", "",
             "## Cinemas covered", ""]
    lines += [f"- {name}: {url}" for name, url in CINEMA_SITES.items()]
    soon = sorted((m for m in movies if m["id"] in upcoming), key=lambda m: upcoming[m["id"]])
    for heading, films in ((f"Films now showing (as of {day})", [m for m in movies if m["id"] not in upcoming]),
                           ("Films coming soon", soon)):
        if not films:
            continue
        lines += ["", f"## {heading}", ""]
        for m in films:
            summary = film_summary(m, upcoming.get(m["id"], ""))
            lines.append(f"- [{m['title']}]({film_url(m['id'], site_url)})" + (f": {summary}" if summary else ""))
    with open(os.path.join(site_dir, "llms.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
