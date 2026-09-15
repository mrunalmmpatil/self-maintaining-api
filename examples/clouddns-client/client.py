"""HTTP access layer for the Google Cloud DNS API."""

import json
import os
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("CLOUDDNS_URL", "https://dns.googleapis.com")
PROJECT = os.environ.get("CLOUDDNS_PROJECT", "example-project")


def _http_get(path):
    """Single seam for all outbound reads, so tests can substitute a transport."""
    with urlopen(f"{BASE_URL}{path}", timeout=5) as response:
        return json.load(response)


def _http_post(path, body):
    """Single seam for all outbound writes."""
    request = Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def _zone_path(zone=""):
    """Base path for managed-zone resources."""
    base = f"/dns/v1/projects/{PROJECT}/managedZones"
    return f"{base}/{zone}" if zone else base


def get_managed_zone(zone):
    return _http_get(_zone_path(zone))


def list_managed_zones():
    return _http_get(_zone_path())


def list_dns_keys(zone):
    return _http_get(f"{_zone_path(zone)}/dnsKeys")


def create_change(zone, body):
    return _http_post(f"{_zone_path(zone)}/changes", body)
