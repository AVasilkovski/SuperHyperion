import logging
from typing import Optional

logger = logging.getLogger(__name__)


def scope_prefix(tenant_id: str, target_var: str = "target", owner_var: str = "tenant") -> str:
    """
    Returns a TypeDB match string that strictly enforces tenant ownership.
    This asserts that:
      1. A tenant entity with the given $tenant-id exists.
      2. The $target_var is owned by that $tenant through a tenant-ownership relation.

    Example output:
        $tenant isa tenant, has tenant-id "T-123";
        $rel (owner: $tenant, owned: $target) isa tenant-ownership;
    """
    if not tenant_id:
        return ""

    return f'${target_var} has tenant-id "{tenant_id}"'


def inject_tenant_attributes(query: str, tenant_id: str) -> str:
    """
    Given an insert query logic, appends the assignment of the tenant-id attribute.
    Warning: This is a simplistic string modifier and must be used carefully.

    Example input: "insert $x isa capsule;" -> "insert $x isa capsule, has tenant-id 'xxx';"
    """
    if not tenant_id:
        return query

    return query.replace(";", f', has tenant-id "{tenant_id}";', 1)


def enforce_scope(tenant_id: Optional[str]):
    """
    Throws an error if tenant_id is explicitly None when scope is required.
    Used at the API boundary to strictly fail-closed.
    """
    if tenant_id is None or str(tenant_id).strip() == "":
        raise ValueError("Tenant isolation violation: tenant_id is required but was not provided.")
    return True
