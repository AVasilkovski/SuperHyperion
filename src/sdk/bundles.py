"""Bundle directory loaders for trust overlays (bundle-only, deterministic)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.graph.contracts import GovernanceSummaryV1
from src.sdk.explainability import ExplainabilitySummaryV1
from src.sdk.types import ReplayVerdictV1


@dataclass(frozen=True)
class BundleView:
    prefix: str
    governance: GovernanceSummaryV1
    replay: Optional[ReplayVerdictV1]
    manifest: Optional[Dict[str, Any]]
    explainability: Optional[ExplainabilitySummaryV1]


@dataclass(frozen=True)
class BundlePaths:
    governance: str
    replay: Optional[str]
    manifest: Optional[str]
    explainability: Optional[str]


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _strip_source_refs(payload: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(payload)
    cleaned.pop("source_refs", None)
    return cleaned


def discover_bundle_paths(bundles_dir: str) -> Dict[str, BundlePaths]:
    files = sorted(f for f in os.listdir(bundles_dir) if f.endswith(".json"))
    grouped: Dict[str, Dict[str, str]] = {}
    suffixes = {
        "_governance_summary.json": "governance",
        "_replay_verify_verdict.json": "replay",
        "_run_capsule_manifest.json": "manifest",
        "_explainability_summary.json": "explainability",
    }
    for name in files:
        for suffix, key in suffixes.items():
            if name.endswith(suffix):
                prefix = name[: -len(suffix)]
                grouped.setdefault(prefix, {})[key] = os.path.join(bundles_dir, name)
                break

    result: Dict[str, BundlePaths] = {}
    for prefix in sorted(grouped):
        item = grouped[prefix]
        if "governance" not in item:
            continue
        result[prefix] = BundlePaths(
            governance=item["governance"],
            replay=item.get("replay"),
            manifest=item.get("manifest"),
            explainability=item.get("explainability"),
        )
    return result


def load_bundle_view(paths: BundlePaths, prefix: str) -> BundleView:
    gov = GovernanceSummaryV1(**_strip_source_refs(_read_json(paths.governance)))
    replay = ReplayVerdictV1(**_strip_source_refs(_read_json(paths.replay))) if paths.replay else None
    manifest = _read_json(paths.manifest) if paths.manifest else None
    explainability = (
        ExplainabilitySummaryV1(**_read_json(paths.explainability))
        if paths.explainability
        else None
    )
    return BundleView(
        prefix=prefix,
        governance=gov,
        replay=replay,
        manifest=manifest,
        explainability=explainability,
    )
