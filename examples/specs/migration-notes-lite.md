# Storefront Inventory API — v1.4.0 to v1.5.0 migration notes

A small, contained release. Two changes only.

## Routing

Product routes moved under `/catalog`. Both the detail route and the listing route are
affected. There is no redirect from the old paths.

## Naming

The product field `name` is now `title`, on both the detail and the listing responses.
This is a transport-level rename only. The storefront's own output key stays `name`;
downstream templates depend on it.

## Unchanged

Money is untouched in this release. `price` and `shipping_price` are both still dollar
amounts and must not be rescaled.
