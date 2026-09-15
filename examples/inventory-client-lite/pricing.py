"""Order pricing and display.

Money crossing this module is a Decimal number of dollars. Formatting to two
decimal places happens once, at the boundary, in quote().
"""

from decimal import Decimal

from client import get_product, list_products


def product_summary(product_id):
    product = get_product(product_id)
    return {
        "name": product["name"],
        "unit_price": Decimal(str(product["price"])),
        "shipping_price": Decimal(str(product["shipping_price"])),
    }


def quote(product_id, quantity):
    if quantity < 0:
        raise ValueError("Quantity must be nonnegative")
    summary = product_summary(product_id)
    unit = summary["unit_price"]
    shipping = summary["shipping_price"]
    return {
        "name": summary["name"],
        "unit_price": f"{unit:.2f}",
        "subtotal": f"{unit * quantity:.2f}",
        "shipping_price": f"{shipping:.2f}",
        "total": f"{unit * quantity + shipping:.2f}",
    }


def catalog_names(category):
    """Display-only listing used by the storefront sidebar."""
    return [product["name"] for product in list_products(category)["items"]]
