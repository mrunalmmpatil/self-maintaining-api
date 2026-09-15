"""Behavioural tests pinned to the Cloud DNS v2 contract.

The transport is stubbed, so these run with no network. They assert what the
console must still report after the migration, not how the client is written.

The environment is configured before the client is imported, so these pass
whether the location is read at import time or at call time.
"""

import os
import unittest
from unittest import mock

os.environ["CLOUDDNS_PROJECT"] = "example-project"
os.environ["CLOUDDNS_LOCATION"] = "europe-west1"

import client  # noqa: E402
import zones  # noqa: E402

ZONE_PREFIX = "/dns/v2/projects/example-project/locations/europe-west1/managedZones"

# Exactly what v2 returns.
V2_ZONE = {"name": "prod-zone", "dnsName": "example.com.", "visibility": "PUBLIC"}

V2_ZONE_LIST = {
    "managedZones": [
        {"name": "prod-zone", "visibility": "PUBLIC"},
        {"name": "internal-zone", "visibility": "PRIVATE"},
    ]
}

V2_DNS_KEYS = {
    "dnsKeys": [
        {"keyTag": 1111, "type": "KEY_SIGNING"},
        {"keyTag": 2222, "type": "ZONE_SIGNING"},
    ]
}

V2_CHANGE = {"id": "42", "status": "DONE"}


class RoutingTest(unittest.TestCase):
    """v2 moved every resource under /locations/{location}."""

    def get_path(self, payload, call):
        with mock.patch.object(client, "_http_get", return_value=dict(payload)) as get:
            call()
            return get.call_args[0][0]

    def test_zone_is_fetched_from_the_v2_location_path(self):
        path = self.get_path(V2_ZONE, lambda: client.get_managed_zone("prod-zone"))
        self.assertEqual(path, f"{ZONE_PREFIX}/prod-zone")

    def test_listing_is_fetched_from_the_v2_location_path(self):
        path = self.get_path(V2_ZONE_LIST, client.list_managed_zones)
        self.assertEqual(path, ZONE_PREFIX)

    def test_dns_keys_are_fetched_from_the_v2_location_path(self):
        path = self.get_path(V2_DNS_KEYS, lambda: client.list_dns_keys("prod-zone"))
        self.assertEqual(path, f"{ZONE_PREFIX}/prod-zone/dnsKeys")

    def test_changes_are_posted_to_the_v2_location_path(self):
        with mock.patch.object(client, "_http_post", return_value=dict(V2_CHANGE)) as post:
            client.create_change("prod-zone", {})
            self.assertEqual(post.call_args[0][0], f"{ZONE_PREFIX}/prod-zone/changes")

    def test_location_is_taken_from_configuration_and_not_invented(self):
        # v2 requires a location and defines no default. The correct value depends
        # on where the project's zones live, so it must come from configuration.
        # A fabricated literal such as "global" fails here.
        path = self.get_path(V2_ZONE_LIST, client.list_managed_zones)
        self.assertIn("/locations/europe-west1/", path + "/")
        self.assertNotIn("/locations/global/", path + "/")


class VisibilityTest(unittest.TestCase):
    """visibility: public -> PUBLIC."""

    def test_public_visibility_uses_the_v2_enum(self):
        with mock.patch.object(client, "_http_get", return_value=dict(V2_ZONE)):
            self.assertIs(zones.zone_summary("prod-zone")["public"], True)

    def test_private_zones_are_excluded_from_the_public_listing(self):
        with mock.patch.object(client, "_http_get", return_value=dict(V2_ZONE_LIST)):
            self.assertEqual(zones.public_zone_names(), ["prod-zone"])

    def test_zone_name_and_dns_name_are_unchanged_fields(self):
        # These field names did not change in v2 and must not be renamed.
        with mock.patch.object(client, "_http_get", return_value=dict(V2_ZONE)):
            summary = zones.zone_summary("prod-zone")
        self.assertEqual(summary["name"], "prod-zone")
        self.assertEqual(summary["dns_name"], "example.com.")


class SigningKeyTest(unittest.TestCase):
    """type: keySigning -> KEY_SIGNING, which is not a plain uppercase."""

    def test_key_signing_keys_use_the_underscored_v2_enum(self):
        # "keySigning".upper() is "KEYSIGNING", which never matches. The v2 value
        # gains an underscore at the word boundary.
        with mock.patch.object(client, "_http_get", return_value=dict(V2_DNS_KEYS)):
            self.assertEqual(zones.signing_key_tags("prod-zone"), [1111])

    def test_zone_signing_keys_are_not_reported(self):
        with mock.patch.object(client, "_http_get", return_value=dict(V2_DNS_KEYS)):
            self.assertNotIn(2222, zones.signing_key_tags("prod-zone"))


class ChangeTest(unittest.TestCase):
    """status: done -> DONE."""

    def test_change_settles_on_the_v2_status_enum(self):
        with mock.patch.object(client, "_http_post", return_value=dict(V2_CHANGE)):
            result = zones.apply_record("prod-zone", "www.example.com.", "A", 300, ["10.0.0.1"])
        self.assertEqual(result["id"], "42")
        self.assertIs(result["settled"], True)

    def test_pending_changes_are_not_reported_as_settled(self):
        pending = {"id": "43", "status": "PENDING"}
        with mock.patch.object(client, "_http_post", return_value=pending):
            result = zones.apply_record("prod-zone", "www.example.com.", "A", 300, ["10.0.0.1"])
        self.assertIs(result["settled"], False)

    def test_record_body_field_names_are_unchanged(self):
        # additions / name / type / ttl / rrdatas are identical in v2.
        # Renaming any of them would be a regression.
        payload = zones.record_payload("www.example.com.", "A", 300, ["10.0.0.1"])
        self.assertEqual(
            payload,
            {
                "additions": [
                    {
                        "name": "www.example.com.",
                        "type": "A",
                        "ttl": 300,
                        "rrdatas": ["10.0.0.1"],
                    }
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
