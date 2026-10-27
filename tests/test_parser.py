import unittest
from pathlib import Path
from unittest import mock

from zepto_scraper import (
    LISTING_FIELDS, PRODUCT_FIELDS, ScrapeError, ZeptoScraper,
    decode_rsc, extract_items, parse_listing, parse_product, subcategory_paths,
)
from zepto_scraper import cli

FIX = Path(__file__).parent / "fixtures"
LISTING = (FIX / "subcategory_page.html").read_text(encoding="utf-8")
PRODUCT = (FIX / "product_page.html").read_text(encoding="utf-8")
CID = "11111111-1111-4111-8111-111111111111"
START = f"https://www.zepto.com/cn/munchies/chips-crisps/cid/{CID}/scid/22222222-2222-4222-8222-222222222220"
V0 = "44444444-4444-4444-8444-444444444440"
PRODUCT_URL = f"https://www.zepto.com/pn/example-snack-0/pvid/{V0}"


class FakeResponse:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class ListingTests(unittest.TestCase):
    def test_decode_joins_chunks(self):
        flat = decode_rsc(LISTING)
        self.assertIn('"endOfPage":true', flat)
        self.assertIn("storeServiceableResponse", flat)

    def test_out_of_stock_cards_are_kept(self):
        items = extract_items(decode_rsc(LISTING))
        self.assertEqual(len(items), 3)  # 2 in stock + 1 out of stock, look-alike skipped
        self.assertEqual(sum(1 for i in items if i.get("outOfStock")), 1)

    def test_prices_are_converted_from_paise(self):
        row = next(r for r in parse_listing(LISTING) if r["variant_id"] == V0)
        self.assertEqual((row["price_inr"], row["mrp_inr"], row["discount_pct"]), (19.0, 20.0, 5))

    def test_row_fields(self):
        row = next(r for r in parse_listing(LISTING) if r["variant_id"] == V0)
        self.assertEqual(list(row), LISTING_FIELDS)
        self.assertEqual(row["available_qty"], 30)
        self.assertEqual((row["rating"], row["rating_count"]), (4.9, 401062))
        self.assertEqual(row["store_id"], "33333333-3333-4333-8333-333333333333")
        self.assertEqual(row["url"], PRODUCT_URL)

    def test_out_of_stock_row(self):
        row = next(r for r in parse_listing(LISTING) if r["name"] == "Example Salted Chips")
        self.assertFalse(row["in_stock"])
        self.assertEqual(row["available_qty"], 0)

    def test_subcategories_dedupe_and_skip_second_slug(self):
        paths = subcategory_paths(LISTING, START)
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(p.startswith("/cn/munchies/") for p in paths))
        self.assertEqual(paths[0], START.split("zepto.com")[1])

    def test_subcategories_need_a_subcategory_url(self):
        with self.assertRaises(ValueError):
            subcategory_paths(LISTING, "https://www.zepto.com/pn/x/pvid/y")


class ProductTests(unittest.TestCase):
    def test_product_sheet(self):
        row = parse_product(PRODUCT, PRODUCT_URL)
        self.assertEqual(list(row), PRODUCT_FIELDS)
        self.assertEqual(row["name"], "Example Chilli Chips")
        self.assertEqual(row["brand"], "Examplo")
        self.assertEqual(row["seller"], "Example Groceries Private Limited")
        self.assertEqual(row["shelf_life"], "180 days")
        self.assertEqual(row["fssai_licence"], "10000000000001")
        self.assertEqual(row["image_count"], 3)

    def test_mrp_and_limit_come_from_the_matching_variant(self):
        row = parse_product(PRODUCT, PRODUCT_URL)
        self.assertEqual((row["mrp_inr"], row["max_per_order"]), (20.0, 30))

    def test_jsonld_with_id_before_type_is_found(self):
        self.assertIn('id="productSchema" type="application/ld+json"', PRODUCT)
        self.assertEqual(parse_product(PRODUCT, PRODUCT_URL)["category"], "Munchies > Chips & Crisps")

    def test_non_product_page_raises(self):
        with self.assertRaises(ValueError):
            parse_product(LISTING, PRODUCT_URL)


class ClientTests(unittest.TestCase):
    def scraper(self, *responses):
        session = mock.Mock()
        session.get.side_effect = list(responses)
        return ZeptoScraper(token="t", session=session, retries=1), session

    def test_202_challenge_is_an_error(self):
        s, _ = self.scraper(FakeResponse(202), FakeResponse(202))
        with mock.patch("time.sleep"), self.assertRaises(ScrapeError) as ctx:
            s.fetch(START)
        self.assertEqual(ctx.exception.status_code, 202)

    def test_client_error_is_not_retried(self):
        s, session = self.scraper(FakeResponse(401))
        with self.assertRaises(ScrapeError):
            s.fetch(START)
        self.assertEqual(session.get.call_count, 1)

    def test_request_uses_indian_residential_proxies(self):
        s, session = self.scraper(FakeResponse(200, LISTING))
        s.fetch(START)
        self.assertEqual(session.get.call_args.kwargs["params"], {"token": "t", "url": START, "super": "true", "geoCode": "in"})

    def test_category_walk_dedupes(self):
        s, session = self.scraper(*[FakeResponse(200, LISTING)] * 3)
        rows = s.get_category(START)
        self.assertEqual(len(rows), 3)
        self.assertEqual(session.get.call_count, 3)  # start page reused, two siblings fetched

    def test_token_required(self):
        with mock.patch.dict("os.environ", {}, clear=True), self.assertRaises(ValueError):
            ZeptoScraper()


class CliTests(unittest.TestCase):
    def test_product_csv_input(self):
        import tempfile, os, csv
        with tempfile.TemporaryDirectory() as d:
            inp, out = os.path.join(d, "in.csv"), os.path.join(d, "out.csv")
            with open(inp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["url"]); w.writeheader(); w.writerow({"url": PRODUCT_URL})
            with mock.patch.object(ZeptoScraper, "fetch", return_value=PRODUCT):
                code = cli.main(["product", "-t", "x", "-i", inp, "-f", "csv", "-o", out])
            self.assertEqual(code, 0)
            self.assertIn("Example Groceries", open(out).read())


if __name__ == "__main__":
    unittest.main()
