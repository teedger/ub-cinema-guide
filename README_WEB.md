# UB Cinema Guide

Scrapes the three Ulaanbaatar cinema chains every day, merges the same film across
cinemas into one entry, and serves a website that shows **which screen shows which
film, at what time, with a direct booking link** wherever the cinema offers one.

| Cinema | Site | Details scraped | Per-show booking link |
|---|---|---|---|
| Urgoo | new.urgoo.mn (urgoo.mn redirects there) | now-showing + films in the schedule, /schedule for up to 7 days | ✅ seat picker per session |
| Tengis | www.tengis.mn | #movies grid, each film page (branch → date → times) | ❌ film page only (the site books via a modal) |
| Prime Cineplex | www.primecineplex.mn | homepage day tabs (today + tomorrow) | ✅ ShoppingCart link per show |

## Files

```
common.py            shared helpers + the common movie/showtime record shape
urgoo.py             Urgoo scraper        -> urgoo.scrape()
tengis.py            Tengis scraper       -> tengis.scrape()
primecineplex.py     Prime scraper        -> primecineplex.scrape()
merge.py             title normalisation + fuzzy matching, one entry per film
watchlist.py         files/my_movies.txt matching + email notification
scraper_ultimate.py  runs all scrapers (in parallel), merges, writes output/latest.json
build_static.py      renders site/ (static copy of the guide) for GitHub Pages
.github/workflows/   daily scrape + deploy to GitHub Pages
web_app.py           Flask site reading output/latest.json
templates/           base.html (shell + styles), index.html (home), film.html (film page), watchlist.html
files/title_aliases.json   manual "this title == that title" overrides
output/latest.json         what the website serves (+ showings_YYYYMMDD.json history)
```

Every scraper returns the same record shape (see the docstring in `common.py`):
a film with `title`, `poster`, `genres`, `duration`, `rating`, `start_date`, and a
list of `showtimes`, each with `date`, `branch`, `hall`, `time`, `format`, `url`.

## Running

```bash
pip install -r requirements.txt          # needs Chrome installed for Selenium

python scraper_ultimate.py               # scrape everything (3–4 minutes), write output/latest.json
python scraper_ultimate.py --notify      # ...and email watchlist matches (MY_EMAIL / MY_PASSWORD env vars)
python urgoo.py out.json                 # run one scraper on its own and dump its raw records

python web_app.py                        # http://localhost:5000
```

Run the scrape daily with cron (adjust the paths):

```
0 9 * * * cd /path/to/Day_12_Urgoo_Cinema && .venv/bin/python scraper_ultimate.py --notify >> output/scrape.log 2>&1
```

The website's **Refresh Data** button runs the same pipeline in the background.

## Free hosting on GitHub Pages

No server, database or login is needed: `.github/workflows/scrape.yml` scrapes the
cinemas on GitHub's runners twice a day (09:00 and 15:00 Ulaanbaatar time),
builds a static page with `build_static.py`, and deploys it to GitHub Pages.
Scraped data is uploaded as a deployment artifact and is never committed, so the
repository stays free of listings, the watchlist and anything personal
(`output/`, `site/` and `files/my_movies.txt` are git-ignored).

One-time setup:

1. Push the repository to GitHub (a public repo gets unlimited Actions minutes).
2. In the repo go to **Settings → Pages** and set **Source** to **GitHub Actions**.
3. Open the **Actions** tab, pick "Scrape cinemas and publish" and press
   **Run workflow**. Every push to `main` also triggers a run.
4. The site appears at `https://<user>.github.io/<repo>/` after the run (about 5 minutes).

If a cinema blocks the runner's IP its badge shows a warning and the other cinemas
still publish; if every scraper fails the build step refuses to deploy and the
previous version stays online. Run the workflow locally with
`python scraper_ultimate.py && python build_static.py` and open `site/index.html`.

## How duplicate films are merged

`merge.py` normalises titles before comparing them: lower case, punctuation
removed, and format words dropped (IMAX, 2D, 3D, 4DX, VIP, Laser, МУСК ...).
Two titles are the same film when the normalised forms are equal, or when they
share a real word and `fuzz.token_set_ratio` is ≥ 90. That handles
`Fall 2` = `Fall 2: Deadpoint`, `The Odyssey` = `The Odyssey IMAX`,
`СҮҮЛЧИЙН ШИЛИЙН САЙН ЭРС` = `Сүүлчийн Шилийн Сайн Эрс`.

When one cinema uses a different-language title (`Zud` vs `Зуд`) or a title fuzzy
matching can't see, add a line to `files/title_aliases.json`:

```json
{ "Тосгон МУСК": "Тосгон", "Zud": "Зуд" }
```

Showtimes of a merged film keep their cinema, branch and hall; a format found in a
cinema's title (`... IMAX`) is attached to that cinema's showtimes.

## Website

The UI follows the "Spotlight" direction from the Claude Design project
(`UB Cinema Guide UI Mockups`): Oswald + Manrope on black, one film lit at a time.

- **Home** (`templates/index.html`): a day strip in the top bar, a spotlight on one
  film (poster, title, cinema → branch → time chips for the chosen day), a cinema
  filter, search, and a poster grid. Clicking a poster moves the spotlight; the title
  or "Full details" opens the film page.
- **Film page** (`templates/film.html`, `/film/<id>` or `site/film/<id>.html`): hero
  with poster and format/rating/duration chips, facts (genre, running time, rating,
  release date, how each cinema lists the title), synopsis, a day strip with cinema
  dots, the full cinema → branch → times list with booking links, a week-at-a-glance
  table, and "also showing" posters.
- Green-bordered time chips open the seat picker for that exact show; the others open
  the film page. Past times are struck through.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/movies` | GET | Merged data (`{scraped_at, date, cinemas, movies}`) |
| `/api/scrape` | POST | Start a scrape in the background |
| `/api/scrape/status` | GET | Scrape progress |
| `/api/watchlist` | GET/POST/DELETE | Manage the watchlist (`{"movie": "..."}`) |
| `/api/watchlist/check` | GET | Watchlist films that are showing now |
