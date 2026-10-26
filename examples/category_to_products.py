"""Walk a Zepto category, then build a catalog sheet for its products.

Usage:
    export SCRAPEDO_TOKEN=your_token
    python category_to_products.py "<subcategory-url>" 10

Writes zepto-category.csv (price, MRP, discount, stock per product) and
zepto-products.csv (seller, shelf life, FSSAI licence for the first N products).
"""

import csv
import sys

from zepto_scraper import LISTING_FIELDS, PRODUCT_FIELDS, ScrapeError, ZeptoScraper


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(start_url: str, max_products: int = 10) -> None:
    scraper = ZeptoScraper()  # reads SCRAPEDO_TOKEN
    listing = scraper.get_category(start_url)
    write("zepto-category.csv", LISTING_FIELDS, listing)
    out_of_stock = sum(1 for row in listing if not row["in_stock"])
    print(f"Saved {len(listing)} products ({out_of_stock} out of stock) to zepto-category.csv")

    products = []
    for row in [r for r in listing if r["url"]][:max_products]:
        try:
            products.append(scraper.get_product(row["url"]))
        except (ScrapeError, ValueError) as exc:
            print(f"skipped {row['url']}: {exc}")
            continue
        print(f"{products[-1]['name']} | {products[-1]['seller']} | shelf life {products[-1]['shelf_life']}")
    write("zepto-products.csv", PRODUCT_FIELDS, products)
    print(f"Saved {len(products)} products to zepto-products.csv")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10)
