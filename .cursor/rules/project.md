# Any Currency to BDT — Project Rules

## Overview

A single Python script (`fetch_rates.py`) that scrapes live BDT exchange rates directly from provider websites, saves raw data to `rates.json`, and generates `README.md`. GitHub Actions runs it daily.

## Tech Stack

- **Python 3.12**
- **aiohttp** — async HTTP client (fast, parallel requests)
- **BeautifulSoup** — HTML parsing for providers without JSON endpoints
- **certifi** — SSL certificates (needed by aiohttp on macOS)
- **GitHub Actions** — daily cron at `00:00 UTC`

## Project Structure

```
any-currency-to-bdt/
├── fetch_rates.py                     # Everything: scrapers, runner, README builder
├── rates.json                         # Auto-generated: raw rate data
├── README.md                          # Auto-generated: markdown tables
├── requirements.txt                   # aiohttp, beautifulsoup4, certifi
├── .github/workflows/update-rates.yml # Daily cron
├── .cursor/rules/project.md           # This file
└── .gitignore
```

## Data Flow

```
scrape providers  →  rates.json  →  README.md
     (parallel)       (committed)    (committed)
```

All 3 steps happen in one `python fetch_rates.py` invocation.

## Key Design Decisions

### One file
Everything lives in `fetch_rates.py` (~230 lines). No multi-file module structure — not needed at this scale and keeps it dead simple to understand and maintain.

### Parallel fetching
All requests (12 currencies × N providers) fire simultaneously via `asyncio.gather`. This brings runtime from ~26s (sequential httpx) down to ~1.4s.

### aiohttp over httpx
Switched from httpx to aiohttp for performance. aiohttp requires explicit SSL context on macOS — handled via `certifi.where()`.

### JSON as intermediate format
`rates.json` is the source of truth. The README is generated from JSON, not from scrape results directly. This means:
- The JSON is a usable data artifact on its own
- README generation is decoupled from scraping
- Both files are committed to the repo

### No third-party rate APIs
Rates come only from the actual provider websites (Wise, Remitly, etc.), never from aggregator APIs like open.er-api.com.

## Provider Details

### Wise
- **Source**: `https://wise.com/rates/live?source={CUR}&target=BDT`
- **Method**: Public JSON endpoint, returns `{"value": 122.2, ...}`
- **Coverage**: All 12 currencies

### Remitly
- **Source**: `https://www.remitly.com/{country}/{lang}/bangladesh`
- **Method**: Server-rendered HTML, rate extracted via regex `(\d{2,4}\.\d{1,6})\s*BDT`
- **Coverage**: USD, GBP, EUR, CAD, AUD (5 regions where Remitly serves Bangladesh)

## Adding a New Provider

1. Write an async function: `async def scrape_xyz(session: aiohttp.ClientSession, src: str) -> Rate | None`
2. Append it to the `SCRAPERS` list
3. The runner and README builder pick it up automatically — no other changes needed

### Provider function contract
- Takes `(session, source_currency_code)` — e.g. `(session, "USD")`
- Returns a `Rate` dataclass on success, `None` on failure
- Must catch all its own exceptions — never crash the script
- Use `aiohttp.ClientTimeout(total=10)` for timeouts

## Coding Conventions

- `from __future__ import annotations` at the top
- Type hints on all functions
- `@dataclass` for data objects
- Rates rounded to 3 decimal places
- No bare `except:` — catch specific exceptions
- Constants in UPPER_SNAKE_CASE
- Section comments with `# ── Name ───` separators

## GitHub Actions

- Cron: `0 0 * * *` (midnight UTC daily)
- Manual trigger: `workflow_dispatch`
- Commits with: `:card_file_box: Update rates: YYYY-MM-DD`
- Commits both `rates.json` and `README.md` via `git add .`

## What NOT to Do

- Don't use third-party exchange rate APIs (open.er-api, exchangerate-api, etc.)
- Don't add API keys or secrets — all scraping uses public endpoints
- Don't split into multiple files unless it exceeds ~300 lines
- Don't add emoji to the README body (title only, keep it clean)
- Don't add sections to README that expose implementation details (providers table, how-it-works diagram, etc.)
