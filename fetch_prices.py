"""
Fetches live prices for every symbol in symbols.json and writes prices.json.

Runs server-side (via GitHub Actions), so Yahoo Finance's lack of CORS support
doesn't matter here — CORS is a browser-only restriction. The dashboard then
reads the resulting prices.json over HTTPS from GitHub, which does send the
right CORS headers for a browser to fetch.

Yahoo's quote endpoint now requires a short-lived "crumb" token obtained via
a cookie handshake first (plain requests get HTTP 401). This does that
handshake, then uses the crumb for the actual batched price request.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import URLError, HTTPError

HERE = Path(__file__).parent
SYMBOLS_FILE = HERE / "symbols.json"
OUTPUT_FILE = HERE / "prices.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
}

_cookie_jar = CookieJar()
_opener = build_opener(HTTPCookieProcessor(_cookie_jar))


def get_crumb():
    """Primes cookies against Yahoo, then exchanges them for an auth crumb."""
    for url in ("https://fc.yahoo.com", "https://query2.finance.yahoo.com"):
        try:
            _opener.open(Request(url, headers=HEADERS), timeout=10).read()
        except Exception:
            pass

    req = Request("https://query2.finance.yahoo.com/v1/test/getcrumb", headers=HEADERS)
    resp = _opener.open(req, timeout=10)
    crumb = resp.read().decode("utf-8").strip()
    if not crumb or "<html" in crumb.lower():
        raise RuntimeError("Did not get a usable crumb from Yahoo")
    return crumb


def fetch_batch(symbols, crumb):
    url = (
        f"https://query1.finance.yahoo.com/v7/finance/quote"
        f"?symbols={','.join(symbols)}&crumb={crumb}"
    )
    req = Request(url, headers=HEADERS)
    with _opener.open(req, timeout=15) as resp:
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

    try:
        crumb = get_crumb()
    except (URLError, HTTPError, TimeoutError, RuntimeError) as e:
        print(f"ERROR: could not obtain auth crumb: {e}", file=sys.stderr)
        return 1

    prices = dict(existing)
    CHUNK = 40
    fetched_any = False

    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        try:
            results = fetch_batch(chunk, crumb)
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
