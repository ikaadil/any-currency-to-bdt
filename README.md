# Any Currency to BDT

Live remittance exchange rates to **Bangladeshi Taka (BDT)**, scraped directly from provider websites.

**Last updated:** `2026-02-19 15:45 UTC`

## Currencies

- [🇺🇸 **USD** — US Dollar](#usd-to-bdt) (2 providers)
- [🇬🇧 **GBP** — British Pound](#gbp-to-bdt) (2 providers)
- [🇪🇺 **EUR** — Euro](#eur-to-bdt) (1 provider)
- [🇨🇦 **CAD** — Canadian Dollar](#cad-to-bdt) (2 providers)
- [🇦🇺 **AUD** — Australian Dollar](#aud-to-bdt) (2 providers)
- [🇸🇬 **SGD** — Singapore Dollar](#sgd-to-bdt) (1 provider)
- [🇦🇪 **AED** — UAE Dirham](#aed-to-bdt) (1 provider)
- [🇲🇾 **MYR** — Malaysian Ringgit](#myr-to-bdt) (1 provider)
- [🇸🇦 **SAR** — Saudi Riyal](#sar-to-bdt) (1 provider)
- [🇰🇼 **KWD** — Kuwaiti Dinar](#kwd-to-bdt) (1 provider)
- [🇶🇦 **QAR** — Qatari Riyal](#qar-to-bdt) (1 provider)
- [🇯🇵 **JPY** — Japanese Yen](#jpy-to-bdt) (1 provider)

## Rates

### USD to BDT

| # | Provider | 1 USD = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/us/currency-converter/usd-to-bdt-rate) | **122.200** | Bank |
| 2 | [Remitly](https://www.remitly.com/us/en/bangladesh) | 121.920 | Bank, Mobile Wallet, Cash Pickup |

### GBP to BDT

| # | Provider | 1 GBP = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Remitly](https://www.remitly.com/gb/en/bangladesh) | **164.890** | Bank, Mobile Wallet, Cash Pickup |
| 2 | [Wise](https://wise.com/gb/currency-converter/gbp-to-bdt-rate) | 164.512 | Bank |

### EUR to BDT

| # | Provider | 1 EUR = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/de/currency-converter/eur-to-bdt-rate) | **143.768** | Bank |

### CAD to BDT

| # | Provider | 1 CAD = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/ca/currency-converter/cad-to-bdt-rate) | **89.272** | Bank |
| 2 | [Remitly](https://www.remitly.com/ca/en/bangladesh) | 89.220 | Bank, Mobile Wallet, Cash Pickup |

### AUD to BDT

| # | Provider | 1 AUD = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Remitly](https://www.remitly.com/au/en/bangladesh) | **87.820** | Bank, Mobile Wallet, Cash Pickup |
| 2 | [Wise](https://wise.com/au/currency-converter/aud-to-bdt-rate) | 86.243 | Bank |

### SGD to BDT

| # | Provider | 1 SGD = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/sg/currency-converter/sgd-to-bdt-rate) | **96.338** | Bank |

### AED to BDT

| # | Provider | 1 AED = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/ae/currency-converter/aed-to-bdt-rate) | **33.269** | Bank |

### MYR to BDT

| # | Provider | 1 MYR = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/my/currency-converter/myr-to-bdt-rate) | **31.265** | Bank |

### SAR to BDT

| # | Provider | 1 SAR = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/sa/currency-converter/sar-to-bdt-rate) | **32.581** | Bank |

### KWD to BDT

| # | Provider | 1 KWD = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/kw/currency-converter/kwd-to-bdt-rate) | **400.065** | Bank |

### QAR to BDT

| # | Provider | 1 QAR = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/qa/currency-converter/qar-to-bdt-rate) | **33.525** | Bank |

### JPY to BDT

| # | Provider | 1 JPY = BDT | Delivery |
|--:|----------|---------------:|----------|
| **1** | [Wise](https://wise.com/jp/currency-converter/jpy-to-bdt-rate) | **0.788** | Bank |

## Providers

| Provider | Source | Method |
|----------|--------|--------|
| [Wise](https://wise.com) | `wise.com/rates/live` | JSON endpoint |
| [Remitly](https://www.remitly.com) | `remitly.com/{region}/en/bangladesh` | HTML scrape |

Adding a provider? Write one async function in `fetch_rates.py` and append it to `SCRAPERS`.

## How it works

```
fetch_rates.py  →  rates.json  →  README.md
     ↑                                 ↑
  scrape providers              generated from JSON
```

A [GitHub Actions cron job](.github/workflows/update-rates.yml) runs this daily at `00:00 UTC` and commits the results.

## Data

Raw rate data is available in [`rates.json`](rates.json) for programmatic use:

```json
{
  "updated_at": "2026-02-19T15:45:14.466599+00:00",
  "target": "BDT",
  "rates": {
    "USD": [
      { "provider": "Wise", "rate": 122.200, ... },
      { "provider": "Remitly", "rate": 121.920, ... }
    ],
    ...
  }
}
```

## Disclaimer

This project is independent and not affiliated with any remittance provider. Rates are scraped from publicly accessible pages and may not reflect actual transfer rates or fees. Always confirm on the provider's website before sending money.

---

*Auto-generated on 2026-02-19 15:45 UTC*
