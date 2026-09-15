"""HTTP access layer for the Storefront Inventory API."""

import json
import os
from urllib.parse import urlencode
from urllib.request import urlopen

BASE_URL = os.environ.get("INVENTORY_URL", "http://inventory.internal:8080")


def _http_get(path):
    """Single seam for all outbound calls, so tests can substitute a transport."""
    with urlopen(f"{BASE_URL}{path}", timeout=5) as response:
        return json.load(response)


def get_product(product_id):
    return _http_get(f"/products/{product_id}")


def list_products(category):
    return _http_get("/products?" + urlencode({"category": category}))
