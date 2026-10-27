# zepto-scraper

[![PyPI](https://img.shields.io/pypi/v/zepto-scraper)](https://pypi.org/project/zepto-scraper/)
[![Python](https://img.shields.io/pypi/pyversions/zepto-scraper)](https://pypi.org/project/zepto-scraper/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Python scraper for [Zepto](https://www.zepto.com), India's quick-commerce grocery app. Two jobs:

- **Category listings:** start from one subcategory URL, walk its sibling subcategories and get every product card with price, MRP, discount, in-stock flag, **units in stock**, rating and the dark store it came from.
- **Product details:** turn product pages into a catalog sheet with seller entity, shelf life, FSSAI licence number, country of origin, category path, order limit and the full description.

Output as Python dicts, JSON or CSV. One dependency (`requests`), no browser.

```bash
pip install zepto-scraper
```

## Why a plain request fails

Zepto sits behind AWS WAF on CloudFront:

| Request | Status | Body |
| --- | --- | --- |
| `requests`, default user agent | 429 | 0 bytes |
| `requests`, Chrome user agent | 202, `x-amzn-waf-action: challenge` | 0 bytes |
| Through Scrape.do, no parameters | 502 after ~60 s (`ROTATION_FAILED`, not charged) | none |
| Through Scrape.do, `super=true&geoCode=in` | 200 in ~3 s | full page |

**Watch the 202.** It means "Accepted", so `raise_for_status()` treats it as success and a scraper that only checks for errors writes empty pages without a single failure. This package treats anything but a 200 as an error.

Pages are fetched through the [Scrape.do](https://scrape.do/?utm_source=github&utm_medium=readme&utm_campaign=zepto-scraper) API through residential proxies in India (`super=true&geoCode=in`), no `render`: 10 credits per page. You need a Scrape.do API token; the free plan includes 1,000 credits a month (about 100 Zepto pages).

## Quick start

```python
from zepto_scraper import ZeptoScraper

scraper = ZeptoScraper(token="YOUR_SCRAPEDO_TOKEN")  # or set SCRAPEDO_TOKEN

# Any subcategory URL; the scraper walks its siblings in the same category
rows = scraper.get_category(
    "https://www.zepto.com/cn/munchies/chips-crisps/cid/d2c2a144-43cd-43e5-b308-92628fa68596/scid/df4f5100-c02f-4906-83b8-ddb744081a7a"
)
for row in rows[:3]:
    print(row["name"], row["price_inr"], row["mrp_inr"], row["in_stock"], row["available_qty"])

product = scraper.get_product(rows[0]["url"])
print(product["seller"], product["shelf_life"], product["fssai_licence"])
```

Start from a **subcategory** URL (`/cn/<category>/<subcategory>/cid/.../scid/...`). The category link on Zepto's homepage is not a listing.

### Command line

```bash
export SCRAPEDO_TOKEN=your_token

# every product in a category, CSV
zepto-scraper category "<subcategory-url>" -f csv -o zepto-category.csv

# catalog sheet for the first 10 products from that file
zepto-scraper product -i zepto-category.csv --limit 10 -f csv -o zepto-products.csv
```

The two commands chain: `product` reads the `url` column of the listing CSV.

### Output

Listing row (from the fictional test page in [`tests/fixtures`](tests/fixtures/subcategory_page.html)):

```json
{
  "variant_id": "44444444-4444-4444-8444-444444444440",
  "name": "Example Chilli Chips",
  "brand": "Examplo",
  "pack_size": "1 pack (41 g)",
  "price_inr": 19.0,
  "mrp_inr": 20.0,
  "discount_pct": 5,
  "in_stock": true,
  "available_qty": 30,
  "rating": 4.9,
  "rating_count": 401062,
  "subcategory": "Chips & Crisps",
  "store_id": "33333333-3333-4333-8333-333333333333",
  "url": "https://www.zepto.com/pn/example-snack-0/pvid/44444444-4444-4444-8444-444444444440"
}
```

Product sheet columns: `variant_id, name, brand, category, pack_size, mrp_inr, max_per_order, rating, rating_count, shelf_life, country_of_origin, seller, fssai_licence, image_count, description, url`.

## How it works

**The Next.js stream.** Zepto runs on the Next.js App Router. A subcategory page makes no separate product API call; every product card is streamed into the HTML as `self.__next_f.push([1, "..."])` chunks. Each chunk is a JavaScript string literal, and JSON strings use the same escaping, so `json.loads('"' + chunk + '"')` decodes it. Joined, the chunks are one text with one JSON object per product card.

**Out-of-stock cards.** Card keys are sorted alphabetically. In-stock cards start with `availableQuantity`; out-of-stock cards drop that key and start with `baseProductId`. A parser that anchors only on `availableQuantity` silently skips every out-of-stock product. This one anchors on both, reads each object with `json.JSONDecoder.raw_decode`, and dedupes on the variant id.

**Prices are in paise.** `"discountedSellingPrice": 1900` is ₹19. The scraper divides by 100.

**Siblings.** Every subcategory page links its siblings, all sharing the category `cid`. The same subcategory can appear under a second category slug that renders no products, so only paths under the start URL's own slug are kept.

**Product pages.** The catalog fields come from the schema.org `Product` JSON-LD block (Zepto writes `id` before `type` on the script tag, so the regex does not depend on attribute order). MRP and the order limit come from the stream's `productVariant` object for the exact variant in the URL.

## Limits

- **32 products per subcategory.** Zepto's web pages stop at 32 cards (`endOfPage: true`) and ignore `?page=2`. For wider coverage, walk more subcategories and categories.
- **One dark store.** Each price and stock count belongs to one dark store. With no location, Zepto serves its default store (east Bengaluru); the `store_id` column records which one. Changing the location through Scrape.do did not move the store in our tests.
- **Use the listing for price and stock.** Product pages cap the stock count and can lag the listing, so `get_product()` leaves price and stock out on purpose.
- **No search.** Search results need a browser-computed `request-signature` header, and robots.txt disallows `/search`. Walk categories instead.
- **Errors.** Non-200 responses (including the 202 challenge) raise `ScrapeError` with the status code. Server errors and 429s are retried twice; client errors are not.

## Responsible use

The scraper reads category (`/cn/`) and product (`/pn/`) pages, which Zepto's robots.txt allows; it does not touch `/search`, `/api/`, cart or account paths. Product data is not personal data. Read Zepto's terms for your use case and keep request rates modest. This is not legal advice.

## Development

```bash
git clone https://github.com/bugrahansss/zepto-scraper
cd zepto-scraper
pip install -e .
python -m unittest discover -s tests -v
```

The tests run offline against fictional fixture pages.

## License

MIT

---

Built and tested with [Scrape.do](https://scrape.do/?utm_source=github&utm_medium=readme&utm_campaign=zepto-scraper), October 2026.
