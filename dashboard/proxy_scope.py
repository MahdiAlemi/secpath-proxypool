"""Central proxy visibility and serialization helpers."""
from __future__ import annotations

from dashboard.decorators import get_current_user, get_user_proxy_filters


SAFE_FILTER_COLUMNS = {
    "id",
    "protocol",
    "ip",
    "port",
    "cost",
    "status",
    "previous_state",
    "last_transition",
    "alive_hits",
    "fail_hits",
    "speed_ms",
    "total_checks",
    "consecutive_fails",
    "latency_score",
    "reliability",
    "jitter_score",
    "recency_score",
    "previous_cost",
    "countryCode",
    "regionName",
    "city",
    "district",
    "zip",
    "isp",
    "org",
    "asn",
    "timezone",
    "last_alive",
    "last_checked",
}


def apply_proxy_scope(query, user=None):
    """Apply status/protocol restrictions for the current authenticated user."""
    user = user if user is not None else get_current_user()
    if not user:
        # Auth decorators normally reject first. Fail closed if called without
        # an authenticated user.
        return query.filter(False)

    from database import Proxy

    filters = get_user_proxy_filters(user)
    if filters.get("statuses"):
        query = query.filter(Proxy.status.in_(filters["statuses"]))
    if filters.get("protocols"):
        query = query.filter(Proxy.protocol.in_(filters["protocols"]))
    return query


def public_proxy_dict(proxy):
    """Serialize a proxy without exposing upstream credentials."""
    data = proxy.to_dict()
    data.pop("username", None)
    data.pop("password", None)
    data["has_auth"] = bool(proxy.username or proxy.password)
    return data


def credential_proxy_dict(proxy):
    """Explicit privileged serializer for controlled exports only."""
    data = proxy.to_dict()
    data["has_auth"] = bool(proxy.username or proxy.password)
    return data
