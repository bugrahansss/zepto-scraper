"""Scrape Zepto category listings and product details with Python."""

from .client import ScrapeError, ZeptoScraper
from .parser import (
    LISTING_FIELDS,
    PRODUCT_FIELDS,
    decode_rsc,
    extract_items,
    parse_listing,
    parse_product,
    subcategory_paths,
)

__all__ = [
    "LISTING_FIELDS",
    "PRODUCT_FIELDS",
    "ScrapeError",
    "ZeptoScraper",
    "decode_rsc",
    "extract_items",
    "parse_listing",
    "parse_product",
    "subcategory_paths",
]

__version__ = "0.1.1"
