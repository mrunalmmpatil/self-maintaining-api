# Storefront Inventory API — v1.4.0 to v2.0.0 migration notes

## Money representation

`price` (dollars, e.g. `89.99`) is replaced by `price_cents` (integer cents, e.g. `8999`).
Divide by 100 to recover dollars. Displayed prices and order totals must be unchanged for
the same product: a product costing 89.99 dollars must still display as `89.99`, and two
of them must still total `179.98`.

`shipping_price` is **not** part of this change. It remains a dollar amount in v2.
Converting it would be a regression.

## Naming

The product field `name` is now `title`, on both the detail and the listing responses.
This is a transport-level rename only. The storefront's own output key stays `name`;
downstream templates depend on it.

## Routing

Product routes moved under `/catalog`. There is no redirect from the old paths.

## Availability

`stock_status` is a new optional response field. We have no use for it yet.
