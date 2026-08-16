"""
Fetches live prices for every symbol in symbols.json and writes prices.json.

Runs server-side (via GitHub Actions), so Yahoo Finance's lack of CORS support
doesn't matter here — CORS is a browser-only restriction. The dashboard then
reads the resulting prices.json over HTTPS from GitHub, which does send the
right CORS headers for a browser to fetch.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

HERE = Path(__file__).parent
SYMBOLS_FILE = HERE / "symbols.json"
OUTPUT_FILE = HERE / "prices.json"

YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioPriceFetcher/1.0)"}


def fetch_batch(symbols):
    url = YAHOO_QUOTE_URL.format(symbols=",".join(symbols))
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("quoteResponse", {}).get("result", [])


def main():
    symbols = json.loads(SYMBOLS_FILE.read_text())
    if not symbols:
        print("No symbols to fetch.")
        return 0

    existing = {}
    if OUTPUT_FILE.exists():
        try:
            existing = json.loads(OUTPUT_FILE.read_text()).get("prices", {})
        except Exception:
            existing = {}

    prices = dict(existing)
    CHUNK = 40
    fetched_any = False

    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        try:
            results = fetch_batch(chunk)
        except (URLError, HTTPError, TimeoutError) as e:
            print(f"WARN: batch fetch failed for {chunk}: {e}", file=sys.stderr)
            continue
        for r in results:
            sym = r.get("symbol")
            price = r.get("regularMarketPrice")
            prev = r.get("regularMarketPreviousClose")
            if sym and price is not None:
                prices[sym] = {"price": price, "prevClose": prev}
                fetched_any = True

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "prices": prices,
    }
    OUTPUT_FILE.write_text(json.dumps(output, indent=2))
    print(f"Wrote {len(prices)} prices to {OUTPUT_FILE}")

    return 0 if fetched_any else 1


if __name__ == "__main__":
    sys.exit(main())
