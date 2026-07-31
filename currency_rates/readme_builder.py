from __future__ import annotations
from datetime import datetime
from currency_rates.config import CURRENCIES


def build_readme(raw: dict) -> str:
    updated = datetime.fromisoformat(raw["updated_at"]).strftime("%Y-%m-%d %H:%M UTC")
    rates_map: dict[str, list[dict]] = raw["rates"]
    lines: list[str] = []

    lines.append("# Best remittance rate to Bangladesh?")
    lines.append("")
    lines.append("I compared Wise, Remitly, Ria, Western Union + 11 more and update it hourly.")
    lines.append("")
    lines.append(f"**Last updated:** `{updated}`")
    lines.append("")
    lines.append("## Why this exists")
    lines.append("")
    lines.append("Sending money to Bangladesh? Provider sites show one rate at a time."
                  " This repo **scrapes 14+ providers** (Wise, Remitly, Ria, Xe,"
                  " Western Union, WorldRemit, SendWave, Paysend, NALA, TapTapSend,"
                  " Instarem, Xoom, OrbitRemit, MoneyGram, nsave) and **ranks them by rate**"
                  " for each currency — so you can pick the best deal in seconds."
                  " Data is refreshed every hour via GitHub Actions. Use the tables"
                  " below or grab [`rates.json`](rates.json) for your own app.")
    lines.append("")
    lines.append("## Rates")
    lines.append("")
    for code, symbol, flag, name in CURRENCIES:
        rates = rates_map.get(code, [])
        lines.append(f"### {code} to BDT")
        lines.append("")
        if not rates:
            lines.append("No rates available.")
            lines.append("")
            continue
        best = rates[0]["rate"]
        has_fee = any(r.get("fee") is not None for r in rates)
        if has_fee:
            lines.append(f"| # | Provider | 1 {code} = BDT | Fee | Delivery |")
            lines.append("|--:|----------|---------------:|-----:|----------|")
        else:
            lines.append(f"| # | Provider | 1 {code} = BDT | Delivery |")
            lines.append("|--:|----------|---------------:|----------|")
        for i, r in enumerate(rates, 1):
            is_best = r["rate"] == best
            rank = f"**{i}**" if is_best else str(i)
            rate_str = f"**{r['rate']:.3f}**" if is_best else f"{r['rate']:.3f}"
            provider_str = f"[{r['provider']}]({r['url']})"
            if has_fee:
                fee_val = r.get("fee")
                fee_str = f"{fee_val:.2f} {code}" if fee_val is not None else "—"
                lines.append(f"| {rank} | {provider_str} | {rate_str} | {fee_str} | {r['delivery']} |")
            else:
                lines.append(f"| {rank} | {provider_str} | {rate_str} | {r['delivery']} |")
        lines.append("")

    lines.append("## Data")
    lines.append("")
    lines.append("Raw rate data is available in [`rates.json`](rates.json)"
                  " for programmatic use:")
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append(f'  "updated_at": "{raw["updated_at"]}",')
    lines.append('  "target": "BDT",')
    lines.append('  "rates": {')
    lines.append('    "USD": [')
    lines.append('      { "provider": "Wise", "rate": 122.200, "fee": null, ... },')
    lines.append('      { "provider": "SendWave", "rate": 121.569, "fee": 0.99, ... }')
    lines.append("    ],")
    lines.append("    ...")
    lines.append("  }")
    lines.append("}")
    lines.append("```")
    lines.append("")

    lines.append("## Disclaimer")
    lines.append("")
    lines.append("This project is independent and not affiliated with any"
                  " remittance provider. Rates and fees are scraped from publicly"
                  " accessible pages and may not reflect actual transfer rates"
                  " or fees. Always confirm on the provider's website before"
                  " sending money.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Auto-generated on {updated}*")
    lines.append("")

    return "\n".join(lines)
