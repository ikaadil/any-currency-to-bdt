# Any Currency to BDT — Project Rules

## Overview

A single Python script that scrapes live remittance exchange rates from provider websites and generates a GitHub README.md. A daily GitHub Actions cron job keeps rates fresh.

## Tech Stack

- **Python 3.11+**, **httpx** (async HTTP), **BeautifulSoup** (HTML parsing)
- **GitHub Actions** for daily cron

## Project Structure

```
any-currency-to-bdt/
├── fetch_rates.py            # The entire app: scrape → rates.json → README.md
├── rates.json                # Auto-generated: raw rate data (committed to repo)
├── requirements.txt          # httpx, beautifulsoup4
├── .github/workflows/
│   └── update-rates.yml      # Daily cron job
├── .gitignore
├── .cursor/rules/project.md  # This file
└── README.md                 # Auto-generated output
```

## How It Works

`fetch_rates.py` contains everything in one file:
1. **Config** — list of currencies (code, symbol, flag, name)
2. **Scrapers** — one async function per provider (e.g. `scrape_wise`, `scrape_remitly`)
3. **Runner** — loops currencies × scrapers, collects results
4. **JSON output** — writes `rates.json` with all rate data and a timestamp
5. **README builder** — reads `rates.json` and generates markdown tables sorted by best rate

## Adding a New Provider

1. Write an `async def scrape_xyz(client, src) -> Rate | None` function
2. Append it to the `SCRAPERS` list
3. That's it — the runner and README builder pick it up automatically

## Scraping Approach

- **Wise**: public JSON endpoint at `wise.com/rates/live?source=X&target=BDT`
- **Remitly**: server-rendered HTML at `remitly.com/{region}/en/bangladesh`, rate extracted via regex
- Each scraper catches its own exceptions and returns `None` on failure
- Failed providers are silently skipped; the README shows whatever succeeded

## Coding Conventions

- Keep it in one file unless it grows past ~300 lines
- Type hints everywhere, `from __future__ import annotations`
- `@dataclass` for data objects
- `async/await` with httpx for all HTTP
- No bare `except:` — always catch specific exceptions
- Provider failures never crash the script

## GitHub Actions

- Runs daily at 06:00 UTC
- Also supports `workflow_dispatch` for manual runs
- Commits updated README.md back to the repo
