"""Command line entry point: ``zepto-scraper category URL`` / ``zepto-scraper product URL ...``."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import List, Optional

from . import __version__
from .client import TOKEN_ENV, ScrapeError, ZeptoScraper
from .parser import LISTING_FIELDS, PRODUCT_FIELDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zepto-scraper",
        description="Scrape Zepto category listings and product details into JSON or CSV.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    cat = sub.add_parser("category", help="Every product in a category, starting from one subcategory URL")
    cat.add_argument("url", help="A Zepto subcategory URL (.../cn/<category>/<subcategory>/cid/.../scid/...)")
    cat.add_argument("--max-subcategories", type=int, default=20)

    prod = sub.add_parser("product", help="Catalog sheet for product pages")
    prod.add_argument("urls", nargs="*", help="Zepto product URLs (.../pn/<slug>/pvid/<id>)")
    prod.add_argument("-i", "--input", help="Text file with one URL per line, or a CSV with a 'url' column")
    prod.add_argument("--limit", type=int, default=0, help="Stop after this many products (0 = all)")

    for p in (cat, prod):
        p.add_argument("-t", "--token", help=f"Scrape.do API token (default: ${TOKEN_ENV})")
        p.add_argument("-f", "--format", choices=("json", "csv"), default="json")
        p.add_argument("-o", "--output", help="Write to this file instead of stdout")
    return parser


def _read_urls(args: argparse.Namespace) -> List[str]:
    urls = list(args.urls)
    if args.input:
        with open(args.input, encoding="utf-8", newline="") as handle:
            if args.input.endswith(".csv"):
                urls.extend(row["url"] for row in csv.DictReader(handle) if row.get("url"))
            else:
                urls.extend(line.strip() for line in handle if line.strip() and not line.startswith("#"))
    return urls[: args.limit] if args.limit else urls


def _write(rows: List[dict], fields: List[str], fmt: str, stream) -> None:
    if fmt == "csv":
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    else:
        json.dump(rows, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        scraper = ZeptoScraper(token=args.token)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    failures = 0
    if args.command == "category":
        fields = LISTING_FIELDS
        try:
            rows = scraper.get_category(args.url, args.max_subcategories)
        except (ScrapeError, ValueError) as exc:
            print(f"fail  {args.url}: {exc}", file=sys.stderr)
            return 1
        out_of_stock = sum(1 for r in rows if not r["in_stock"])
        print(f"{len(rows)} products, {out_of_stock} out of stock", file=sys.stderr)
    else:
        fields = PRODUCT_FIELDS
        urls = _read_urls(args)
        if not urls:
            print("No URLs given. Pass product URLs or --input FILE.", file=sys.stderr)
            return 2
        rows = []
        for url in urls:
            try:
                rows.append(scraper.get_product(url))
                print(f"ok    {url}", file=sys.stderr)
            except (ScrapeError, ValueError) as exc:
                failures += 1
                print(f"fail  {url}: {exc}", file=sys.stderr)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="" if args.format == "csv" else None) as handle:
            _write(rows, fields, args.format, handle)
        print(f"Saved {len(rows)} rows to {args.output}", file=sys.stderr)
    else:
        _write(rows, fields, args.format, sys.stdout)
    return 1 if failures and not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
