import json
import unittest
from unittest.mock import patch

import tracker

SAMPLE_DOCUMENTS = (
    {
        "E": {
            "ap-isog-east-1": {
                "arnPartition": "aws-iso-g",
                "regionName": "ap-isog-east-1",
            },
            "me-central-2": {"arnPartition": "aws", "regionName": "me-central-2"},
        },
        "M": {
            "aws-iso-g": {
                "partitionLeader": "ap-isog-east-1",
                "consoleRootDomain": "console.csphome.adc-g.au",
            },
            "aws-iso-f": {"partitionLeader": "us-isof-south-1"},
            "aws-cn": {"partitionLeader": "cn-north-1"},
            "aws-iso": {"partitionLeader": "us-iso-east-1"},
            "aws": {
                "partitionLeader": "us-east-1",
                "consoleRootDomain": "console.aws.amazon.com",
            },
            "aws-iso-b": {"partitionLeader": "us-isob-east-1"},
            "aws-iso-e": {"partitionLeader": "eu-isoe-west-1"},
            "aws-us-gov": {"partitionLeader": "us-gov-west-1"},
            "aws-eusc": {"partitionLeader": "eusc-de-east-1"},
        },
    },
    {
        "ap-isog-east-1": {
            "arnPartition": "aws-iso-g",
            "pAuthEndpointByStageMap": {
                "prod": "ap-isog-east-1.console.csphome.adc-g.au",
            },
        },
    },
)


def sample_snapshot(timestamp):
    snapshot = tracker.empty_snapshot(timestamp)
    for document in SAMPLE_DOCUMENTS:
        tracker.ingest_object(snapshot, document)
    tracker.finalize(snapshot)
    return snapshot


class TrackerTests(unittest.TestCase):
    def test_ingest_object_normalizes_sample_documents(self):
        snapshot = sample_snapshot("2026-09-04T00:00:00Z")

        self.assertEqual("aws-iso-g", snapshot["regions"]["ap-isog-east-1"]["partition"])
        self.assertEqual(
            "ap-isog-east-1.console.csphome.adc-g.au",
            snapshot["regions"]["ap-isog-east-1"]["pAuthEndpoints"]["prod"],
        )
        self.assertEqual(
            "console.aws.amazon.com", snapshot["partitions"]["aws"]["consoleRootDomain"]
        )
        self.assertIn("me-central-2", snapshot["partitions"]["aws"]["regions"])
        self.assertEqual(9, len(snapshot["partitions"]))

    def test_portal_extractor_handles_json_parse_and_raw_objects(self):
        snapshot = tracker.empty_snapshot("2026-09-04T00:00:00Z")
        script = r"""const a=JSON.parse('{"E":{"xx-test-1":{"arnPartition":"aws-test","regionName":"xx-test-1"}},"M":{"aws-test":{"partitionLeader":"xx-test-1","consoleRootDomain":"console.example"}}}');
        const b={"xx-test-1":{websiteDomain:"example.test",websiteDomainDualstack:"dual.example.test"}};"""

        tracker.extract_portal_text(snapshot, script)
        tracker.finalize(snapshot)

        self.assertEqual("aws-test", snapshot["regions"]["xx-test-1"]["partition"])
        self.assertEqual("example.test", snapshot["regions"]["xx-test-1"]["websiteDomain"])
        self.assertEqual("console.example", snapshot["partitions"]["aws-test"]["consoleRootDomain"])

    def test_portal_extractor_ingests_region_metadata_and_airport_maps(self):
        snapshot = tracker.empty_snapshot("2026-09-04T00:00:00Z")
        script = """const regions=[{
            regionName:"us-isob-east-1",
            regionLongName:"US ISOB East (Ohio)",
            airportCode:"LCK",
            optIn:!1,
            arnPartition:"aws-iso-b",
            status:"GA",
            services:{ec2:!0,sts:!0,polaroid:!1}
        }];
        const airportRegions={FRA:"eu-central-1"};
        const pairs=[{airportCode:"AKL",regionName:"ap-southeast-6"}];
        const endpoints={"us-isob-east-1":{
            websiteDomain:"sc2shome.sgov.gov",
            websiteDomainDualstack:"awshome.scloud",
            devDomain:"aws-dev.sc2shome.sgov.gov",
            pAuthEndpointByStageMap:{
                preprod:"us-isob-east-1.awsc-integ.sc2shome.sgov.gov",
                prod:"us-isob-east-1.console.sc2shome.sgov.gov"
            },
            pAuthDualStackEndpointByStageMap:{
                preprod:"us-isob-east-1.awsc-integ.awshome.scloud"
            },
            services:{
                signin:{prodish:{url:"us-isob-east-1.aws-signin-testing.sgov.gov"}},
                consolehome:{isLaunched:!0,pathSlug:"console"}
            }
        }};
        const control={"us-isob-east-1":{
            fallbackRegion:"us-isob-east-1",
            dualstackEndpoint:"us-isob-east-1.ccs.console.api.aws"
        }};"""

        observed_regions = tracker.extract_portal_text(snapshot, script)

        region = snapshot["regions"]["us-isob-east-1"]
        self.assertEqual(3, observed_regions)
        self.assertEqual("US ISOB East (Ohio)", region["regionLongName"])
        self.assertEqual("LCK", region["airportCode"])
        self.assertFalse(region["optIn"])
        self.assertEqual("aws-iso-b", region["partition"])
        self.assertEqual("GA", region["status"])
        self.assertEqual(
            {"ec2": True, "sts": True, "polaroid": False},
            region["consoleServiceSupport"],
        )
        self.assertEqual("FRA", snapshot["regions"]["eu-central-1"]["airportCode"])
        self.assertEqual("AKL", snapshot["regions"]["ap-southeast-6"]["airportCode"])
        self.assertEqual("aws-dev.sc2shome.sgov.gov", region["developmentDomain"])
        self.assertEqual(
            "us-isob-east-1.awsc-integ.sc2shome.sgov.gov",
            region["pAuthEndpoints"]["preprod"],
        )
        self.assertEqual(
            "us-isob-east-1.awsc-integ.awshome.scloud",
            region["pAuthDualStackEndpoints"]["preprod"],
        )
        self.assertEqual("us-isob-east-1", region["consoleFallbackRegion"])
        self.assertEqual("us-isob-east-1.ccs.console.api.aws", region["consoleControlEndpoint"])
        self.assertEqual(
            "us-isob-east-1.aws-signin-testing.sgov.gov",
            region["consoleServices"]["signin"]["endpoints"]["prodish"],
        )
        self.assertEqual(
            {"isLaunched": True, "pathSlug": "console"},
            region["consoleServices"]["consolehome"],
        )

    def test_ip_ranges_preserve_aggregate_regional_evidence(self):
        document = {
            "syncToken": "123",
            "createDate": "2026-09-11-00-00-00",
            "prefixes": [
                {
                    "ip_prefix": "15.248.168.0/21",
                    "region": "sa-west-1",
                    "service": "AMAZON",
                    "network_border_group": "sa-west-1",
                },
                {
                    "ip_prefix": "15.248.168.0/21",
                    "region": "sa-west-1",
                    "service": "EC2",
                    "network_border_group": "sa-west-1",
                },
            ],
            "ipv6_prefixes": [
                {
                    "ipv6_prefix": "2600:1f00:8000::/40",
                    "region": "sa-west-1",
                    "service": "AMAZON",
                    "network_border_group": "sa-west-1",
                }
            ],
        }
        snapshot = tracker.empty_snapshot("2026-09-11T00:00:00Z")

        with patch.object(
            tracker,
            "fetch",
            return_value=(
                json.dumps(document).encode(),
                tracker.IP_RANGES_URL,
            ),
        ):
            tracker.enrich_from_ip_ranges(snapshot)

        network = snapshot["regions"]["sa-west-1"]["network"]
        self.assertEqual(2, network["ipv4PrefixCount"])
        self.assertEqual(1, network["ipv6PrefixCount"])
        self.assertEqual(["AMAZON", "EC2"], network["services"])
        self.assertEqual(["sa-west-1"], network["networkBorderGroups"])
        self.assertNotIn("ipv4Prefixes", network)
        self.assertNotIn("ipv6Prefixes", network)
        self.assertEqual("123", snapshot["sources"][0]["version"])

    def test_portal_extractor_counts_regions_from_all_paths(self):
        snapshot = tracker.empty_snapshot("2026-09-04T00:00:00Z")
        script = r"""const a=JSON.parse('{"json-test-1":{"arnPartition":"aws-test"}}');
        const b={"domain-test-1":{websiteDomain:"example.test",websiteDomainDualstack:"dual.example.test"}};
        const c={"pair-test-1":"aws-test"};"""

        observed_regions = tracker.extract_portal_text(snapshot, script)

        self.assertEqual(3, observed_regions)

    def test_ingestion_rejects_console_domains_as_partition_ids(self):
        snapshot = tracker.empty_snapshot("2026-09-04T00:00:00Z")
        script = r"""e.exports = JSON.parse(
                '{"us-isob-east-1":"awsc-integ.sc2shome.sgov.gov"}'
            );"""

        tracker.extract_portal_text(snapshot, script)

        self.assertNotIn("awsc-integ.sc2shome.sgov.gov", snapshot["partitions"])

    def test_portal_discovery_accepts_preexisting_regions(self):
        snapshot = tracker.empty_snapshot("2026-09-04T00:00:00Z")
        tracker.merge_region(snapshot, "xx-test-1", {"partition": "aws-test"})
        payload = (
            b'const regions={"xx-test-1":{websiteDomain:"example.test",'
            b'websiteDomainDualstack:"dual.example.test"}};'
        )

        with (
            patch.object(
                tracker,
                "PORTAL_SEEDS",
                ("https://example.test/portal.js",),
            ),
            patch.object(
                tracker,
                "fetch",
                return_value=(payload, "https://example.test/portal.js"),
            ),
        ):
            tracker.discover_portal(snapshot)

        self.assertEqual(
            {
                "assetsScanned": 1,
                "kind": "aws-portal-assets",
                "regionsObserved": 1,
                "url": "https://example.test/portal.js",
            },
            snapshot["sources"][0],
        )

    def test_portal_discovery_follows_absolute_javascript_urls(self):
        seed_url = "https://prod.pa.cdn.uis.awsstatic.com/panorama-nav-init.js"
        child_url = "https://a.b.cdn.console.awsstatic.com/a/v1/build/awsc-head.32.js"
        payloads = {
            seed_url: (
                f'const child = "{child_url}"; const regions = {{"seed-test-1":"aws-test"}};'
            ).encode(),
            child_url: (
                b"""e.exports = JSON.parse(
                    '{"us-isob-closed-1":"aws-iso-b"}'
                );"""
            ),
        }
        requested = []

        def fetch(url):
            requested.append(url)
            return payloads[url], url

        snapshot = tracker.empty_snapshot("2026-09-04T00:00:00Z")
        with (
            patch.object(tracker, "PORTAL_SEEDS", (seed_url,)),
            patch.object(tracker, "fetch", side_effect=fetch),
        ):
            tracker.discover_portal(snapshot)

        self.assertEqual([seed_url, child_url], requested)
        self.assertEqual("aws-iso-b", snapshot["regions"]["us-isob-closed-1"]["partition"])
        self.assertEqual(2, snapshot["sources"][0]["assetsScanned"])
        self.assertEqual(2, snapshot["sources"][0]["regionsObserved"])

    def test_change_detection_ignores_retrieval_metadata(self):
        before = sample_snapshot("2026-09-03T00:00:00Z")
        after = sample_snapshot("2026-09-04T00:00:00Z")
        after["sources"] = [{"kind": "different-run"}]

        changes = tracker.calculate_changes(before, after)

        self.assertFalse(changes["changed"])

    def test_change_detection_reports_new_partition_and_region(self):
        before = sample_snapshot("2026-09-03T00:00:00Z")
        after = sample_snapshot("2026-09-04T00:00:00Z")
        tracker.merge_region(after, "xx-test-1", {"partition": "aws-test"})
        tracker.finalize(after)

        changes = tracker.calculate_changes(before, after)

        self.assertEqual(["aws-test"], changes["addedPartitions"])
        self.assertEqual(["xx-test-1"], changes["addedRegions"])


if __name__ == "__main__":
    unittest.main()
