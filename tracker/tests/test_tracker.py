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

    def test_portal_extractor_counts_regions_from_all_paths(self):
        snapshot = tracker.empty_snapshot("2026-09-04T00:00:00Z")
        script = r"""const a=JSON.parse('{"json-test-1":{"arnPartition":"aws-test"}}');
        const b={"domain-test-1":{websiteDomain:"example.test",websiteDomainDualstack:"dual.example.test"}};
        const c={"pair-test-1":"aws-test"};"""

        observed_regions = tracker.extract_portal_text(snapshot, script)

        self.assertEqual(3, observed_regions)

    def test_portal_discovery_accepts_preexisting_regions(self):
        snapshot = tracker.empty_snapshot("2026-09-04T00:00:00Z")
        tracker.merge_region(snapshot, "xx-test-1", {"partition": "aws-test"})
        payload = (
            b'const regions={"xx-test-1":{websiteDomain:"example.test",'
            b'websiteDomainDualstack:"dual.example.test"}};'
        )

        with patch.object(
            tracker,
            "PORTAL_SEEDS",
            ("https://example.test/portal.js",),
        ), patch.object(
            tracker,
            "fetch",
            return_value=(payload, "https://example.test/portal.js"),
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
