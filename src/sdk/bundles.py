"""Bundle directory loaders for trust overlays (bundle-only, deterministic)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote

from src.graph.contracts import GovernanceSummaryV1
from src.sdk.explainability import ExplainabilitySummaryAny, parse_explainability_summary
from src.sdk.types import ReplayVerdictV1


@dataclass(frozen=True)
class BundleView:
    prefix: str
    bundle_key: str
    governance: GovernanceSummaryV1
    replay: Optional[ReplayVerdictV1]
    manifest: Optional[Dict[str, Any]]
    explainability: Optional[ExplainabilitySummaryAny]
    tenant_id: Optional[str]
    effective_tenant_id: str
    capsule_id: Optional[str]


@dataclass(frozen=True)
class BundlePaths:
    prefix: str
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


def _bundle_tenant_id(
    governance: Dict[str, Any], manifest: Optional[Dict[str, Any]]
) -> Optional[str]:
    tenant = None
    if manifest is not None:
        tenant = manifest.get("tenant_id")
    if tenant is None:
        tenant = governance.get("tenant_id")
    return str(tenant) if tenant is not None else None


def _effective_tenant_id(raw_tenant_id: Optional[str]) -> str:
    return raw_tenant_id if raw_tenant_id is not None else "default"


def output_prefix(bundle: BundleView) -> str:
    normalized = bundle.bundle_key.replace("\\", "/")
    return quote(normalized, safe="")


def discover_bundle_paths(
    bundles_dir: str, tenant_id: Optional[str] = None
) -> Dict[str, BundlePaths]:
    grouped: Dict[str, Dict[str, str]] = {}
    files: list[str] = []
    for root, dirs, filenames in os.walk(bundles_dir):
        dirs.sort()
        for name in sorted(filenames):
            if name.endswith(".json"):
                files.append(os.path.join(root, name))

    suffixes = {
        "_governance_summary.json": "governance",
        "_replay_verify_verdict.json": "replay",
        "_run_capsule_manifest.json": "manifest",
        "_explainability_summary.json": "explainability",
    }
    for path in files:
        name = os.path.basename(path)
        rel_dir = os.path.relpath(os.path.dirname(path), bundles_dir)
        rel_dir = rel_dir.replace("\\", "/")
        for suffix, key in suffixes.items():
            if name.endswith(suffix):
                prefix = name[: -len(suffix)]
                bundle_key = prefix if rel_dir == "." else f"{rel_dir}/{prefix}"
                grouped.setdefault(bundle_key, {"prefix": prefix})[key] = path
                break

    result: Dict[str, BundlePaths] = {}
    for bundle_key in sorted(grouped):
        item = grouped[bundle_key]
        if "governance" not in item:
            continue
        if tenant_id is not None:
            governance = _strip_source_refs(_read_json(item["governance"]))
            manifest = _read_json(item["manifest"]) if "manifest" in item else None
            bundle_tenant = _bundle_tenant_id(governance, manifest)
            if _effective_tenant_id(bundle_tenant) != tenant_id:
                continue
        result[bundle_key] = BundlePaths(
            prefix=str(item["prefix"]),
            governance=item["governance"],
            replay=item.get("replay"),
            manifest=item.get("manifest"),
            explainability=item.get("explainability"),
        )
    return result


def load_bundle_view(paths: BundlePaths, bundle_key: str) -> BundleView:
    gov_payload = _strip_source_refs(_read_json(paths.governance))
    gov = GovernanceSummaryV1(**gov_payload)
    replay = (
        ReplayVerdictV1(**_strip_source_refs(_read_json(paths.replay))) if paths.replay else None
    )
    manifest = _read_json(paths.manifest) if paths.manifest else None
    explainability = (
        parse_explainability_summary(_read_json(paths.explainability))
        if paths.explainability
        else None
    )
    raw_tenant_id = _bundle_tenant_id(gov_payload, manifest)
    return BundleView(
        prefix=paths.prefix,
        bundle_key=bundle_key,
        governance=gov,
        replay=replay,
        manifest=manifest,
        explainability=explainability,
        tenant_id=raw_tenant_id,
        effective_tenant_id=_effective_tenant_id(raw_tenant_id),
        capsule_id=str((manifest or {}).get("capsule_id"))
        if (manifest or {}).get("capsule_id") is not None
        else None,
    )


def load_bundles(bundles_dir: str, tenant_id: Optional[str] = None) -> list[BundleView]:
    bundle_paths = discover_bundle_paths(bundles_dir, tenant_id=tenant_id)
    bundles = [
        load_bundle_view(bundle_paths[bundle_key], bundle_key)
        for bundle_key in sorted(bundle_paths)
    ]
    bundles.sort(key=lambda b: (b.effective_tenant_id, (b.capsule_id or ""), b.bundle_key))
    return bundles
