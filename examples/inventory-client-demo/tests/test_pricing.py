"""Behavioural tests pinned to the Inventory API v2 contract (fully automatable migration).

The transport is stubbed, so these run with no network. They assert what the
storefront must still show after the migration, not how the client is written.
"""

import unittest
from unittest import mock

import client
import pricing

# Exactly what v2 returns for product 1.
V2_PRODUCT = {
    "id": 1,
    "title": "Mechanical Keyboard",
    "price_cents": 8999,
    "shipping_price": 4.50,
    "stock_status": "in_stock",
}

V2_LISTING = {"items": [{"id": 1, "title": "Mechanical Keyboard"}, {"id": 2, "title": "USB-C Hub"}]}


class QuoteTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(client, "_http_get", return_value=dict(V2_PRODUCT))
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    def requested_path(self):
        return self.get.call_args[0][0]

    def test_product_is_fetched_from_the_v2_catalog_path(self):
        client.get_product(1)
        self.assertEqual(self.requested_path(), "/catalog/products/1")

    def test_unit_price_is_displayed_in_dollars(self):
        # 8999 cents must display as 89.99 dollars, never as 8999.00.
        self.assertEqual(pricing.quote(1, 1)["unit_price"], "89.99")

    def test_subtotal_multiplies_the_converted_price(self):
        self.assertEqual(pricing.quote(1, 2)["subtotal"], "179.98")

    def test_shipping_price_is_still_dollars_and_is_not_converted(self):
        # shipping_price did NOT change units in v2. Converting it would be a regression.
        self.assertEqual(pricing.quote(1, 2)["shipping_price"], "4.50")

    def test_total_combines_converted_price_with_unconverted_shipping(self):
        self.assertEqual(pricing.quote(1, 2)["total"], "184.48")

    def test_display_key_stays_name_even_though_the_api_field_is_title(self):
        # The storefront's own output contract must not follow the API rename.
        self.assertEqual(pricing.quote(1, 1)["name"], "Mechanical Keyboard")

    def test_zero_quantity_still_charges_shipping(self):
        quote = pricing.quote(1, 0)
        self.assertEqual(quote["subtotal"], "0.00")
        self.assertEqual(quote["total"], "4.50")

    def test_negative_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            pricing.quote(1, -1)


class CatalogListingTest(unittest.TestCase):
    def test_listing_reads_the_renamed_field(self):
        with mock.patch.object(client, "_http_get", return_value=dict(V2_LISTING)):
            self.assertEqual(pricing.catalog_names("peripherals"), ["Mechanical Keyboard", "USB-C Hub"])


if __name__ == "__main__":
    unittest.main()
