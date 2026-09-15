"""Zone and change reporting for the DNS console.

Enum values crossing this module are the API's own strings, compared literally.
A change in how the API spells them changes what this module reports.
"""

from client import create_change, get_managed_zone, list_dns_keys, list_managed_zones

PUBLIC_VISIBILITY = "public"
SIGNING_KEY_TYPE = "keySigning"
SETTLED_STATUS = "done"


def zone_summary(zone):
    managed = get_managed_zone(zone)
    return {
        "name": managed["name"],
        "dns_name": managed["dnsName"],
        "public": managed["visibility"] == PUBLIC_VISIBILITY,
    }


def public_zone_names():
    """Names of the externally resolvable zones, for the console sidebar."""
    zones = list_managed_zones()["managedZones"]
    return [zone["name"] for zone in zones if zone["visibility"] == PUBLIC_VISIBILITY]


def signing_key_tags(zone):
    """Key-signing keys only. Zone-signing keys are not reported here."""
    keys = list_dns_keys(zone)["dnsKeys"]
    return [key["keyTag"] for key in keys if key["type"] == SIGNING_KEY_TYPE]


def record_payload(name, record_type, ttl, rrdatas):
    """Request body for a record addition."""
    return {
        "additions": [
            {"name": name, "type": record_type, "ttl": ttl, "rrdatas": rrdatas}
        ]
    }


def apply_record(zone, name, record_type, ttl, rrdatas):
    change = create_change(zone, record_payload(name, record_type, ttl, rrdatas))
    return {"id": change["id"], "settled": change["status"] == SETTLED_STATUS}
