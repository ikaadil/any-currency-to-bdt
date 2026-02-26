# Best remittance rate to Bangladesh? — Project Rules

## Overview

A single Python script (`fetch_rates.py`) that scrapes live BDT exchange rates and fees directly from provider websites, saves raw data to `rates.json`, and generates `README.md`. GitHub Actions runs it hourly.

## Tech Stack

- **Python 3.12**
- **aiohttp** — async HTTP client (fast, parallel requests)
- **BeautifulSoup** — HTML parsing for providers without JSON endpoints
- **certifi** — SSL certificates (needed by aiohttp on macOS)
- **playwright** — headless Chromium for Western Union, WorldRemit, Xoom
- **scrapling[fetchers]** — stealth browser (Scrapling) for Ria
- **GitHub Actions** — hourly cron

## Project Structure

```
any-currency-to-bdt/
├── fetch_rates.py                     # Everything: scrapers, runner, README builder
├── rates.json                         # Auto-generated: raw rate data
├── README.md                          # Auto-generated: markdown tables
├── requirements.txt                   # aiohttp, beautifulsoup4, certifi, playwright, scrapling[fetchers]
├── .github/workflows/update-rates.yml # Hourly cron
├── .cursor/rules/project.md           # This file
└── .gitignore
```

## Data Flow

```
scrape providers  →  rates.json  →  README.md
     (parallel)       (committed)    (committed)
```

All 3 steps happen in one `python fetch_rates.py` invocation.

## Architecture

### Provider base class

All scrapers inherit from `Provider(ABC)`. The base class handles:

- **Auto-registration** via `__init_subclass__` — no manual list to maintain
- **Error handling** — `scrape()` wraps `fetch_rate()` in try/except
- **Rate construction** — builds `Rate(name, url, rate, delivery, fee)` automatically; `fee` is optional
- **Caching** — providers that batch-load rates store cache as instance state

### Adding a new provider

Subclass `Provider`, set three class attributes, implement one method:

```python
class MyProvider(Provider):
    name     = "MyProvider"                  # display name
    url      = "https://example.com/bd"      # default provider URL
    delivery = "Bank"                        # delivery methods

    async def fetch_rate(self, session, src):
        # Return a float (the BDT rate), (rate, fee), or None if unavailable.
        async with session.get(f"https://api.example.com/{src}", timeout=TIMEOUT) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            rate = data.get("rate")
            fee = data.get("fee")  # optional
            return (rate, fee) if fee is not None else rate
```

Optional overrides:
- `get_url(src)` — return a currency-specific URL (default: `self.url`)
- `__init__` — add a `self._cache` dict for providers that batch-load

### Provider contract

- `fetch_rate(session, src)` receives an `aiohttp.ClientSession` and source currency code (e.g. `"USD"`)
- Return a `float`, or `(rate, fee)` when fee is available, or `None` on failure (corridor not supported, API error, etc.)
- Raise freely — the base class `scrape()` catches all exceptions
- Use the module-level `TIMEOUT` constant for request timeouts
- Use `TARGET` constant (`"BDT"`) instead of hardcoding the string

### One file

Everything lives in `fetch_rates.py`. No multi-file module structure — not needed at this scale and keeps it dead simple to understand and maintain.

### Parallel fetching

All requests (12 currencies × N providers) fire simultaneously via `asyncio.gather`. This brings runtime from ~26s (sequential httpx) down to ~1.5s.

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
- **Coverage**: USD, GBP, CAD, AUD (regions where Remitly serves Bangladesh)

### TapTapSend
- **Source**: `https://api.taptapsend.com/api/fxRates`
- **Method**: Public JSON API, single call returns all corridors; cached per run
- **Coverage**: USD, GBP, EUR, CAD, AUD, AED (corridors with BDT destination)
- **Headers required**: `Appian-Version`, `X-Device-Id`, `X-Device-Model`

### NALA
- **Source**: `https://partners-api.prod.nala-api.com/v1/fx/rates`
- **Method**: Public JSON API, returns rates for multiple providers; filter by `provider_name == "NALA"` and `destination_currency == "BDT"`; cached per run
- **Coverage**: USD, GBP, EUR

### Instarem
- **Source**: `https://www.instarem.com/wp-json/instarem/v2/convert-rate/{src}/`
- **Method**: WordPress REST API, returns conversion rates from source currency to all destinations; extract `BDT` from response
- **Coverage**: All 12 currencies (mid-market rates)

### Providers and methods
- **HTTP (API or HTML)**: Wise, Remitly, TapTapSend, NALA, Instarem, SendWave (API; returns fee), Paysend (HTML; fee from page), **Xe** (currency converter; mid-market, all 12), **OrbitRemit** (AUD/NZD→BDT converter HTML)
- **Playwright (browser)**: Western Union, WorldRemit, Xoom (JS-rendered; no public API)
- **Scrapling (stealth browser)**: Ria (rates-conversion), **MoneyGram** (corridor page; best-effort __NEXT_DATA__), **nsave** (calculator; best-effort)
- **Not integrated**: Elevate Pay (rate only in app)

## Coding Conventions

- `from __future__ import annotations` at the top
- Type hints on all functions
- `@dataclass` for data objects
- Rates rounded to 3 decimal places
- No bare `except:` — catch specific exceptions
- Constants in UPPER_SNAKE_CASE
- Section comments with `# ── Name ───` separators
- Provider-specific constants as class attributes (prefixed `_` if internal)

## GitHub Actions

- Cron: `0 * * * *` (hourly)
- Manual trigger: `workflow_dispatch`
- Commits with: `:card_file_box: Update rates: YYYY-MM-DD HH UTC`
- Commits both `rates.json` and `README.md` via `git add .`
- Playwright Chromium cached; `install-deps` runs each time. Scrapling (Ria, MoneyGram) uses the same Chromium via patchright; we do not run `scrapling install` in CI (Camoufox download from GitHub often times out)

## What NOT to Do

- Don't use third-party exchange rate APIs (open.er-api, exchangerate-api, etc.)
- Don't add API keys or secrets — all scraping uses public endpoints
- Don't split into multiple files unless it exceeds ~300 lines
- Don't add emoji to the README body (title only, keep it clean)
- Don't add sections to README that expose implementation details (providers table, how-it-works diagram, etc.)
