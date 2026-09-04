#!/usr/bin/env python3
"""Collect AWS partition/region metadata exposed by AWS web applications."""

from __future__ import annotations

import argparse
import ast
import copy
import datetime as dt
import html.parser
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "current.json"
CHANGES_PATH = ROOT / "data" / "changes" / "latest.json"

PORTAL_SEEDS = (
    "https://console.aws.amazon.com/",
    "https://prod.pa.cdn.uis.awsstatic.com/panorama-nav-init.js",
    # The public console shell redirects unauthenticated crawlers to sign-in.
    # This content-addressed bootstrap remains a direct fallback for region metadata.
    "https://a.b.cdn.console.awsstatic.com/a/v1/3ELRO6TRPCNJ7JQCUM33Z4GYAV24JX5OOKYVXFTH7TAAKC5LQUBA/awsc-head.32.js",
)
REGIONAL_TABLE_URL = "https://api.regional-table.region-services.aws.a2z.com/index.json"
BOTCORE_PARTITIONS_URL = (
    "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/partitions.json"
)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36 AWSDataTracker/1.0"
)
REGION_RE = re.compile(r"^[a-z][a-z0-9-]+-\d+$")
PARTITION_RE = re.compile(r"^aws(?:-[a-z]+)*$")
SCRIPT_URL_RE = re.compile(
    r"""["'](?P<url>(?:(?:https?:)?//|/|\.{1,2}/|static/)[^"']+?\.(?:js|mjs)(?:[?#][^"']*)?)["']"""
)
PORTAL_ASSET_HOST_SUFFIX = ".awsstatic.com"


class ScriptParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        src = dict(attrs).get("src")
        if src:
            self.scripts.append(src)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch(url: str, timeout: int = 30) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.geturl()


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    temporary.replace(path)


def empty_snapshot(timestamp: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "retrievedAt": timestamp,
        "sources": [],
        "partitions": {},
        "regions": {},
    }


def clean_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items() if item is not None}


def ensure_partition(snapshot: dict[str, Any], partition_id: str) -> dict[str, Any]:
    partitions = snapshot["partitions"]
    return partitions.setdefault(partition_id, {"id": partition_id, "regions": []})


def infer_partition(
    snapshot: dict[str, Any], region: str, website_domain: str | None = None
) -> str:
    known = snapshot["regions"].get(region, {}).get("partition")
    if known:
        return known
    for partition_id, partition in snapshot["partitions"].items():
        if website_domain and partition.get("websiteDomain") == website_domain:
            return partition_id
    prefixes = (
        ("us-isob-", "aws-iso-b"),
        ("us-isof-", "aws-iso-f"),
        ("us-iso-", "aws-iso"),
        ("eu-isoe-", "aws-iso-e"),
        ("ap-isog-", "aws-iso-g"),
        ("us-gov-", "aws-us-gov"),
        ("eusc-", "aws-eusc"),
        ("cn-", "aws-cn"),
    )
    return next((partition for prefix, partition in prefixes if region.startswith(prefix)), "aws")


def merge_region(snapshot: dict[str, Any], region_id: str, values: dict[str, Any]) -> None:
    if not REGION_RE.match(region_id):
        return
    region = snapshot["regions"].setdefault(region_id, {"id": region_id})
    region.update(clean_mapping(values))
    partition_id = region.get("partition") or infer_partition(
        snapshot, region_id, region.get("websiteDomain")
    )
    region["partition"] = partition_id
    ensure_partition(snapshot, partition_id)


def ingest_object(
    snapshot: dict[str, Any],
    value: Any,
    observed_regions: set[str] | None = None,
) -> None:
    if isinstance(value, list):
        for item in value:
            ingest_object(snapshot, item, observed_regions)
        return
    if not isinstance(value, dict):
        return

    for key, item in value.items():
        if REGION_RE.match(str(key)) and isinstance(item, dict):
            fields: dict[str, Any] = {}
            for source, target in (
                ("arnPartition", "partition"),
                ("regionName", "regionName"),
                ("websiteDomain", "websiteDomain"),
                ("websiteDomainDualstack", "websiteDomainDualstack"),
                ("pAuthEndpointByStageMap", "pAuthEndpoints"),
                ("upsEndpointByStageMap", "upsEndpoints"),
            ):
                if source in item:
                    fields[target] = item[source]
            if fields:
                region_id = str(key)
                merge_region(snapshot, region_id, fields)
                if observed_regions is not None:
                    observed_regions.add(region_id)
        elif (
            PARTITION_RE.fullmatch(str(key))
            and isinstance(item, dict)
            and ("partitionLeader" in item or "consoleRootDomain" in item)
        ):
            partition = ensure_partition(snapshot, str(key))
            partition.update(clean_mapping(item))
        elif REGION_RE.match(str(key)) and isinstance(item, str) and PARTITION_RE.fullmatch(item):
            region_id = str(key)
            merge_region(snapshot, region_id, {"partition": item})
            if observed_regions is not None:
                observed_regions.add(region_id)
        ingest_object(snapshot, item, observed_regions)


def extract_json_parse_values(script: str) -> Iterable[Any]:
    pattern = re.compile(r"JSON\.parse\(((?:'(?:\\.|[^'\\])*')|(?:\"(?:\\.|[^\"\\])*\"))\)")
    for match in pattern.finditer(script):
        try:
            decoded = ast.literal_eval(match.group(1))
            yield json.loads(decoded)
        except (SyntaxError, ValueError, json.JSONDecodeError):
            continue


def extract_script_urls(script: str) -> Iterable[str]:
    for match in SCRIPT_URL_RE.finditer(script):
        yield match.group("url")


def is_portal_asset_url(candidate: str, base_url: str) -> bool:
    parsed = urllib.parse.urlparse(candidate)
    base = urllib.parse.urlparse(base_url)
    hostname = parsed.hostname
    return bool(
        parsed.scheme == "https"
        and hostname
        and (hostname == base.hostname or hostname.endswith(PORTAL_ASSET_HOST_SUFFIX))
    )


def extract_portal_text(snapshot: dict[str, Any], script: str) -> int:
    observed_regions: set[str] = set()
    for value in extract_json_parse_values(script):
        ingest_object(snapshot, value, observed_regions)
    region_domains = re.compile(
        r'["\'](?P<region>[a-z][a-z0-9-]+-\d+)["\']\s*:\s*\{'
        r'[^{}]{0,500}?websiteDomain\s*:\s*["\'](?P<domain>[^"\']+)["\']\s*,'
        r'[^{}]{0,300}?websiteDomainDualstack\s*:\s*["\'](?P<dual>[^"\']+)["\']'
    )
    for match in region_domains.finditer(script):
        region_id = match.group("region")
        observed_regions.add(region_id)
        merge_region(
            snapshot,
            region_id,
            {
                "websiteDomain": match.group("domain"),
                "websiteDomainDualstack": match.group("dual"),
            },
        )

    partition_pairs = re.compile(
        r'["\'](?P<region>[a-z][a-z0-9-]+-\d+)["\']\s*:\s*["\'](?P<partition>aws(?:-[a-z]+)*)["\']'
    )
    for match in partition_pairs.finditer(script):
        region_id = match.group("region")
        observed_regions.add(region_id)
        merge_region(snapshot, region_id, {"partition": match.group("partition")})
    return len(observed_regions)


def discover_portal(snapshot: dict[str, Any], max_scripts: int = 80) -> None:
    queue = list(PORTAL_SEEDS)
    visited: set[str] = set()
    successful: list[str] = []
    observed_regions = 0
    while queue and len(visited) < max_scripts:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            payload, final_url = fetch(url)
        except (OSError, urllib.error.URLError):
            continue
        text = payload.decode("utf-8", errors="replace")
        successful.append(final_url)
        observed_regions += extract_portal_text(snapshot, text)

        content_parser = ScriptParser()
        content_parser.feed(text)
        if not content_parser.scripts and final_url.startswith(
            "https://console.aws.amazon.com/console/home"
        ):
            separator = "&" if "?" in final_url else "?"
            oauth_start = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
            queue.append(f"{final_url}{separator}hashArgs=%23&oauthStart={oauth_start}")
        for source in content_parser.scripts:
            candidate = urllib.parse.urljoin(final_url, source)
            if candidate.startswith("https://") and candidate not in visited:
                queue.append(candidate)
        for relative in re.findall(
            r'["\']([^"\']+(?:_buildManifest|static/chunks/[^"\']+)\.js)["\']', text
        ):
            candidate = urllib.parse.urljoin(final_url, relative)
            if candidate.startswith("https://") and candidate not in visited:
                queue.append(candidate)
        for source in extract_script_urls(text):
            candidate = urllib.parse.urljoin(final_url, source)
            if is_portal_asset_url(candidate, final_url) and candidate not in visited:
                queue.append(candidate)

    if not successful or not observed_regions:
        raise RuntimeError("AWS portal assets contained no recognizable region metadata")
    snapshot["sources"].append(
        {
            "kind": "aws-portal-assets",
            "url": PORTAL_SEEDS[0],
            "assetsScanned": len(successful),
            "regionsObserved": observed_regions,
        }
    )


def enrich_from_botocore(snapshot: dict[str, Any]) -> None:
    payload, final_url = fetch(BOTCORE_PARTITIONS_URL)
    document = json.loads(payload)
    for raw_partition in document.get("partitions", []):
        partition_id = raw_partition["id"]
        partition = ensure_partition(snapshot, partition_id)
        partition["regionRegex"] = raw_partition.get("regionRegex")
        outputs = raw_partition.get("outputs", {})
        for key in ("name", "dnsSuffix", "dualStackDnsSuffix", "implicitGlobalRegion"):
            if key in outputs:
                partition[key] = outputs[key]
        for region_id, region_data in raw_partition.get("regions", {}).items():
            merge_region(
                snapshot,
                region_id,
                {
                    "partition": partition_id,
                    "description": region_data.get("description"),
                },
            )
    snapshot["sources"].append(
        {
            "kind": "botocore-partitions",
            "url": final_url,
            "version": document.get("version"),
        }
    )


def enrich_from_regional_table(snapshot: dict[str, Any]) -> None:
    payload, final_url = fetch(REGIONAL_TABLE_URL)
    document = json.loads(payload)
    services: defaultdict[str, dict[str, str]] = defaultdict(dict)
    for price in document.get("prices", []):
        attributes = price.get("attributes", {})
        region_id = attributes.get("aws:region")
        name = attributes.get("aws:serviceName")
        if region_id and name:
            services[region_id][name] = attributes.get("aws:serviceUrl", "")
    for region_id, items in services.items():
        merge_region(
            snapshot,
            region_id,
            {
                "services": [{"name": name, "url": url} for name, url in sorted(items.items())],
                "serviceCount": len(items),
            },
        )
    metadata = document.get("metadata", {})
    snapshot["sources"].append(
        {
            "kind": "aws-regional-services-table",
            "url": final_url,
            "version": metadata.get("source:version"),
            "disclaimer": metadata.get("disclaimer"),
        }
    )


def finalize(snapshot: dict[str, Any]) -> None:
    for partition in snapshot["partitions"].values():
        partition["regions"] = []
    for region_id, region in snapshot["regions"].items():
        partition_id = region.get("partition") or infer_partition(
            snapshot, region_id, region.get("websiteDomain")
        )
        region["partition"] = partition_id
        ensure_partition(snapshot, partition_id)["regions"].append(region_id)
    for partition in snapshot["partitions"].values():
        partition["regions"] = sorted(set(partition["regions"]))
        partition["regionCount"] = len(partition["regions"])


def comparable(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {"partitions": {}, "regions": {}}
    result = copy.deepcopy(snapshot)
    result.pop("retrievedAt", None)
    result.pop("sources", None)
    return result


def calculate_changes(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any]:
    old = comparable(before)
    new = comparable(after)
    added_partitions = sorted(set(new["partitions"]) - set(old["partitions"]))
    removed_partitions = sorted(set(old["partitions"]) - set(new["partitions"]))
    added_regions = sorted(set(new["regions"]) - set(old["regions"]))
    removed_regions = sorted(set(old["regions"]) - set(new["regions"]))
    changed_regions = sorted(
        region
        for region in set(old["regions"]) & set(new["regions"])
        if old["regions"][region] != new["regions"][region]
    )
    changed_partitions = sorted(
        partition
        for partition in set(old["partitions"]) & set(new["partitions"])
        if old["partitions"][partition] != new["partitions"][partition]
    )
    return {
        "changed": bool(
            added_partitions
            or removed_partitions
            or added_regions
            or removed_regions
            or changed_regions
            or changed_partitions
        ),
        "addedPartitions": added_partitions,
        "removedPartitions": removed_partitions,
        "addedRegions": added_regions,
        "removedRegions": removed_regions,
        "changedPartitions": changed_partitions,
        "changedRegions": changed_regions,
    }


def set_action_outputs(changes: dict[str, Any]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    summary_parts = []
    for key in (
        "addedPartitions",
        "addedRegions",
        "removedPartitions",
        "removedRegions",
        "changedPartitions",
        "changedRegions",
    ):
        if changes[key]:
            summary_parts.append(f"{key}: {', '.join(changes[key])}")
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"changed={'true' if changes['changed'] else 'false'}\n")
        handle.write(f"summary={' | '.join(summary_parts) or 'No metadata changes'}\n")


def update(allow_partial: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    before = load_json(DATA_PATH)
    timestamp = utc_now()
    snapshot = empty_snapshot(timestamp) if before is None else copy.deepcopy(before)
    snapshot["retrievedAt"] = timestamp
    snapshot["sources"] = []

    operations = (discover_portal, enrich_from_botocore, enrich_from_regional_table)
    failures: list[str] = []
    for operation in operations:
        try:
            operation(snapshot)
        except Exception as error:  # noqa: BLE001 - source independence is intentional
            failures.append(f"{operation.__name__}: {error}")
    if failures and not allow_partial:
        raise RuntimeError("; ".join(failures))
    if failures:
        snapshot["sourceErrors"] = failures
    else:
        snapshot.pop("sourceErrors", None)

    finalize(snapshot)
    changes = calculate_changes(before, snapshot)
    changes["retrievedAt"] = timestamp
    write_json(DATA_PATH, snapshot)
    write_json(CHANGES_PATH, changes)
    if changes["changed"] and before is not None:
        history_name = timestamp.replace(":", "-") + ".json"
        write_json(ROOT / "data" / "history" / history_name, snapshot)
    set_action_outputs(changes)
    return snapshot, changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    update_parser = subparsers.add_parser("update", help="retrieve and persist current metadata")
    update_parser.add_argument(
        "--allow-partial", action="store_true", help="write data when an enrichment source fails"
    )
    args = parser.parse_args(argv)

    snapshot, changes = update(args.allow_partial)
    print(
        json.dumps(
            {
                "partitions": len(snapshot["partitions"]),
                "regions": len(snapshot["regions"]),
                "changed": changes["changed"],
                "changes": changes,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
