"""Behavioural tests pinned to the Inventory API v1.5.0 contract.

The transport is stubbed, so these run with no network.
"""

import unittest
from unittest import mock

import client
import pricing

# Exactly what v1.5.0 returns for product 1. Prices are still dollars.
V2_PRODUCT = {"id": 1, "title": "Mechanical Keyboard", "price": 89.99, "shipping_price": 4.50}

V2_LISTING = {"items": [{"id": 1, "title": "Mechanical Keyboard"}, {"id": 2, "title": "USB-C Hub"}]}


class QuoteTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(client, "_http_get", return_value=dict(V2_PRODUCT))
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    def test_product_is_fetched_from_the_catalog_path(self):
        client.get_product(1)
        self.assertEqual(self.get.call_args[0][0], "/catalog/products/1")

    def test_listing_is_fetched_from_the_catalog_path(self):
        client.list_products("peripherals")
        self.assertTrue(self.get.call_args[0][0].startswith("/catalog/products?"))

    def test_display_key_stays_name_even_though_the_api_field_is_title(self):
        self.assertEqual(pricing.quote(1, 1)["name"], "Mechanical Keyboard")

    def test_prices_are_unchanged_dollars(self):
        quote = pricing.quote(1, 2)
        self.assertEqual(quote["unit_price"], "89.99")
        self.assertEqual(quote["subtotal"], "179.98")
        self.assertEqual(quote["shipping_price"], "4.50")
        self.assertEqual(quote["total"], "184.48")

    def test_negative_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            pricing.quote(1, -1)


class CatalogListingTest(unittest.TestCase):
    def test_listing_reads_the_renamed_field(self):
        with mock.patch.object(client, "_http_get", return_value=dict(V2_LISTING)):
            self.assertEqual(pricing.catalog_names("peripherals"), ["Mechanical Keyboard", "USB-C Hub"])


if __name__ == "__main__":
    unittest.main()
