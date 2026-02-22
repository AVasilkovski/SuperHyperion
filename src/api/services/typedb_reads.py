"""
TRUST-1.2 TypeDB Read Services
Provides strictly read-only, tenant-isolated data access.
"""

import base64
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from src.db.typedb_client import TypeDBConnection

logger = logging.getLogger(__name__)


def _encode_cursor(capsule_id: str, created_at: str) -> str:
    """Opaque cursor encoding."""
    data = {"capsule_id": capsule_id, "created_at": created_at}
    json_str = json.dumps(data)
    return base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor_str: str) -> Dict[str, str]:
    """Decode and validate an opaque cursor."""
    try:
        json_str = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        data = json.loads(json_str)
        if not isinstance(data, dict) or "capsule_id" not in data or "created_at" not in data:
            raise ValueError("Malformed cursor structure")
        return data
    except Exception as e:
        logger.warning(f"Invalid pagination cursor: {e}")
        raise HTTPException(status_code=400, detail="Invalid pagination cursor")


def list_capsules_for_tenant(
    tenant_id: str, limit: int = 50, cursor: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    List capsules scoped to a tenant with cursor pagination.
    Uses strict tenant-owns-capsule joins. No writes permitted.
    """
    # Defensive limit capping
    actual_limit = max(1, min(limit, 200))

    cursor_clause = ""
    if cursor:
        cursor_data = _decode_cursor(cursor)
        c_time = cursor_data["created_at"]
        c_id = cursor_data["capsule_id"]
        # For descending sort (created_at DESC, capsule_id DESC), the next page must be strictly older
        # or exactly the same time but a strictly smaller id.
        cursor_clause = f"""
        {{ $c has created-at $ca; $ca < "{c_time}"; }} or
        {{ $c has created-at "{c_time}"; $c has capsule-id $cid; $cid < "{c_id}"; }};
        """

    # NOTE: In TypeDB 3.x querying, explicit disjunction might require specific syntax.
    # If TypeQL 'or' is not supported exactly like this in all drivers, the fallback
    # is to fetch a slightly larger window and sort/filter in Python.
    # For robust MVP, we will rely on TypeQL if supported, else rely on sorting.

    query = f"""
    match
        $t isa tenant, has tenant-id "{tenant_id}";
        $rel (tenant: $t, capsule: $c) isa tenant-owns-capsule;
        $c isa run-capsule,
            has capsule-id $cid,
            has session-id $sid,
            has created-at $ca;
        $c has query-hash $qh;
        $c has scope-lock-id $slid;
        $c has intent-id $iid;
        $c has proposal-id $pid;
        {cursor_clause}
    fetch
        $c: capsule-id, session-id, query-hash, scope-lock-id, intent-id, proposal-id, created-at;
    """

    db = TypeDBConnection()

    if getattr(db, "_mock_mode", False):
        return [], None

    try:
        # We enforce TransactionType.READ to guarantee no side-effects
        from typedb.driver import TransactionType

        with db.transaction(TransactionType.READ) as tx:
            raw_rows = db._to_rows(db._tx_execute(tx, query))

            # Application-level stable sort (created-at DESC, capsule-id DESC)
            # In case the TypeDB engine does not natively order the fetch output
            results = []
            for r in raw_rows:
                # the fetch syntax might return dicts like:
                # r = {'capsule-id': ['capsule-123'], 'created-at': ['2026-...'], ...}
                # Normalize keys into flat values
                normalized = {}
                for k, v in r.items():
                    k_clean = k.replace("-", "_")
                    normalized[k_clean] = v[0] if isinstance(v, list) and v else v

                # Make sure mandatory fields exist
                if "capsule_id" in normalized and "created_at" in normalized:
                    results.append(normalized)

            results.sort(
                key=lambda x: (x.get("created_at", ""), x.get("capsule_id", "")), reverse=True
            )

            # Note: We must also filter cursor manually if TypeQL `or` is tricky.
            if cursor:
                cursor_data = _decode_cursor(cursor)
                c_time = cursor_data["created_at"]
                c_id = cursor_data["capsule_id"]
                filtered_results = []
                for item in results:
                    item_time = item.get("created_at", "")
                    item_id = item.get("capsule_id", "")
                    # Return items strictly older/smaller than the cursor
                    if item_time < c_time or (item_time == c_time and item_id < c_id):
                        filtered_results.append(item)
                results = filtered_results

            page_items = results[:actual_limit]
            has_next = len(results) > actual_limit

            next_cursor_str = None
            if has_next and page_items:
                last_item = page_items[-1]
                next_cursor_str = _encode_cursor(last_item["capsule_id"], last_item["created_at"])

            return page_items, next_cursor_str

    except Exception as e:
        logger.error(f"TypeDB Query Error in list_capsules_for_tenant: {e}")
        # Fail closed for any DB error; DO NOT leak info
        return [], None


def fetch_capsule_by_id_scoped(tenant_id: str, capsule_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a single capsule manifest by ID, ensuring it belongs to the specified tenant.
    Returns None if the capsule does not exist OR if it belongs to a different tenant.
    No writes permitted.
    """
    query = f"""
    match
        $t isa tenant, has tenant-id "{tenant_id}";
        $c isa run-capsule, has capsule-id "{capsule_id}";
        $rel (tenant: $t, capsule: $c) isa tenant-owns-capsule;
    fetch
        $c: capsule-id, session-id, query-hash, scope-lock-id, intent-id, proposal-id, created-at, manifest-version;
    """

    db = TypeDBConnection()

    if getattr(db, "_mock_mode", False):
        return None

    try:
        from typedb.driver import TransactionType

        with db.transaction(TransactionType.READ) as tx:
            raw_rows = db._to_rows(db._tx_execute(tx, query))

            if not raw_rows:
                return None

            r = raw_rows[0]
            normalized = {}
            for k, v in r.items():
                k_clean = k.replace("-", "_")
                normalized[k_clean] = v[0] if isinstance(v, list) and v else v

            return normalized

    except Exception as e:
        logger.error(f"TypeDB Query Error in fetch_capsule_by_id_scoped: {e}")
        return None
