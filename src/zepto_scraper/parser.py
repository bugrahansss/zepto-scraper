"""Parse Zepto category and product pages.

Zepto runs on the Next.js App Router. Every product card on a subcategory page
is streamed into the HTML as React Server Components payload, a series of
``self.__next_f.push([1, "..."])`` script chunks. Product pages carry the same
stream plus a schema.org ``Product`` block in JSON-LD.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

ZEPTO = "https://www.zepto.com"

PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
# Card keys are sorted alphabetically. In-stock cards start with availableQuantity;
# out-of-stock cards drop that key and start with baseProductId.
ITEM_START_RE = re.compile(r'\{"(?:availableQuantity|baseProductId)":')
PRODUCT_URL_RE = re.compile(r"https://www\.zepto\.com/pn/[a-z0-9-]+/pvid/[0-9a-f-]{36}")
STORE_RE = re.compile(r'"storeServiceableResponse":\{[^}]*?"storeId":"([0-9a-f-]{36})"')
LD_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)

LISTING_FIELDS = [
    "variant_id", "name", "brand", "pack_size", "price_inr", "mrp_inr", "discount_pct",
    "in_stock", "available_qty", "rating", "rating_count", "subcategory", "store_id", "url",
]
PRODUCT_FIELDS = [
    "variant_id", "name", "brand", "category", "pack_size", "mrp_inr", "max_per_order",
    "rating", "rating_count", "shelf_life", "country_of_origin", "seller", "fssai_licence",
    "image_count", "description", "url",
]

_decoder = json.JSONDecoder()


def decode_rsc(html: str) -> str:
    """Join the Next.js stream chunks back into one text.

    Each chunk is a JavaScript string literal; JSON strings use the same escaping,
    so ``json.loads('"' + chunk + '"')`` gives back the original text.
    """
    return "".join(json.loads('"' + chunk + '"') for chunk in PUSH_RE.findall(html))


def rupees(paise) -> object:
    """Zepto stores every price in paise: 1900 means Rs 19."""
    return paise / 100 if isinstance(paise, (int, float)) and not isinstance(paise, bool) else ""


def extract_items(flat: str) -> List[dict]:
    """Return every product card in a decoded stream, in-stock and out-of-stock."""
    items: Dict[str, dict] = {}
    for match in ITEM_START_RE.finditer(flat):
        try:
            obj, _ = _decoder.raw_decode(flat, match.start())
        except json.JSONDecodeError:
            continue
        variant = obj.get("productVariant") or {}
        # Look-alike objects elsewhere in the stream have no product block
        if variant.get("id") and obj.get("product"):
            items.setdefault(variant["id"], obj)
    return list(items.values())


def product_urls(flat: str) -> Dict[str, str]:
    """The page's own product links, keyed by variant id."""
    return {link.rsplit("/", 1)[1]: link for link in PRODUCT_URL_RE.findall(flat)}


def store_id(flat: str) -> str:
    match = STORE_RE.search(flat)
    return match.group(1) if match else ""


def to_row(item: dict, store: str, urls: Dict[str, str]) -> dict:
    product = item.get("product") or {}
    variant = item.get("productVariant") or {}
    rating = variant.get("ratingSummary") or {}
    return {
        "variant_id": variant.get("id", ""),
        "name": product.get("name", ""),
        "brand": product.get("brand", ""),
        "pack_size": variant.get("formattedPacksize", ""),
        "price_inr": rupees(item.get("discountedSellingPrice")),
        "mrp_inr": rupees(item.get("mrp")),
        "discount_pct": item.get("discountPercent", 0),
        "in_stock": not item.get("outOfStock", False),
        "available_qty": item.get("availableQuantity", 0),
        "rating": rating.get("averageRating", ""),
        "rating_count": rating.get("totalRatings", ""),
        "subcategory": item.get("primarySubcategoryName", ""),
        "store_id": store,
        "url": urls.get(variant.get("id", ""), ""),
    }


def parse_listing(html: str) -> List[dict]:
    """Every product card on one subcategory page, as flat rows."""
    flat = decode_rsc(html)
    store = store_id(flat)
    urls = product_urls(flat)
    return [to_row(item, store, urls) for item in extract_items(flat)]


def subcategory_paths(html: str, start_url: str) -> List[str]:
    """The start subcategory plus its siblings, as site paths, deduped on scid.

    The same subcategory can appear under a second category slug that renders no
    products, so only paths under the start URL's own category slug are kept.
    """
    cid_match = re.search(r"/cid/([0-9a-f-]{36})", start_url)
    if not cid_match or "/cn/" not in start_url:
        raise ValueError("Start from a Zepto subcategory URL (.../cn/<category>/<subcategory>/cid/.../scid/...)")
    cid = cid_match.group(1)
    sub_re = re.compile(r"/cn/[a-z0-9-]+/[a-z0-9-]+/cid/" + cid + r"/scid/[0-9a-f-]{36}")
    category_slug = start_url.split("/cn/")[1].split("/")[0]
    start_path = "/cn/" + start_url.split("/cn/", 1)[1].split("?")[0]
    found: Dict[str, str] = {}
    for path in [start_path] + sub_re.findall(decode_rsc(html)):
        if path.split("/")[2] == category_slug:
            found.setdefault(path.rsplit("/", 1)[1], path)
    return list(found.values())


def product_jsonld(html: str) -> dict:
    """The schema.org Product block (the page has several JSON-LD blocks)."""
    for block in LD_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return {}


def variant_data(flat: str, variant_id: str) -> dict:
    """productVariant carries the printed MRP and order limit for this pack size."""
    for match in re.finditer(r'"productVariant":\{', flat):
        try:
            obj, _ = _decoder.raw_decode(flat, match.end() - 1)
        except json.JSONDecodeError:
            continue
        if obj.get("id") == variant_id:
            return obj
    return {}


def parse_product(html: str, url: str) -> dict:
    """Catalog sheet for one product page.

    Price and stock are left out on purpose: the product page caps the stock
    count and can lag the listing. Use the listing for those.
    """
    ld = product_jsonld(html)
    if not ld:
        raise ValueError("No Product JSON-LD on the page; it is probably not a Zepto product page")
    variant_id = url.rstrip("/").rsplit("/", 1)[1]
    variant = variant_data(decode_rsc(html), variant_id)
    rating = ld.get("aggregateRating") or {}
    props = {p.get("name"): p.get("value") for p in ld.get("additionalProperty", []) if isinstance(p, dict)}
    images = ld.get("image") or []
    return {
        "variant_id": variant_id,
        "name": ld.get("name", ""),
        "brand": (ld.get("brand") or {}).get("name", "") if isinstance(ld.get("brand"), dict) else ld.get("brand", ""),
        "category": ld.get("category", ""),
        "pack_size": ld.get("size", ""),
        "mrp_inr": rupees(variant.get("mrp")),
        "max_per_order": variant.get("maxAllowedQuantity", ""),
        "rating": rating.get("ratingValue", ""),
        "rating_count": rating.get("ratingCount", ""),
        "shelf_life": props.get("Shelf life", ""),
        "country_of_origin": props.get("Country of origin", ""),
        "seller": props.get("Seller", ""),
        "fssai_licence": props.get("FSSAI licence number", ""),
        "image_count": len(images) if isinstance(images, list) else 1,
        "description": ld.get("description", ""),
        "url": url,
    }
