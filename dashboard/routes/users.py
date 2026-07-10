import re

import bcrypt
from flask import Blueprint, jsonify, request, session as flask_session

from dashboard.config import ALL_PERMISSIONS, ROLE_PERMISSIONS
from dashboard.security import api_error

from dashboard.decorators import (
    get_user_permissions,
    login_required,
    require_permission,
)
from database import Token, User, db

users_bp = Blueprint("users", __name__)


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
_PROXY_STATUSES = {"alive", "flaky", "soft", "cooling", "dead", "revived", "semi-revived", "untested"}
_PROXY_PROTOCOLS = {"http", "https", "socks4", "socks5"}


def _normalize_custom_permissions(value):
    if value is None:
        return {}, None
    if not isinstance(value, dict):
        return None, "custom_permissions must be an object"
    unknown = set(value) - {"add", "remove", "proxy_filters"}
    if unknown:
        return None, "custom_permissions contains unsupported keys"

    normalized = {}
    for key in ("add", "remove"):
        entries = value.get(key, [])
        if not isinstance(entries, list):
            return None, f"custom_permissions.{key} must be an array"
        entries = [str(item) for item in entries]
        if any(item not in ALL_PERMISSIONS for item in entries):
            return None, f"custom_permissions.{key} contains an unknown permission"
        normalized[key] = sorted(set(entries))

    filters = value.get("proxy_filters", {})
    if not isinstance(filters, dict):
        return None, "proxy_filters must be an object"
    if set(filters) - {"statuses", "protocols"}:
        return None, "proxy_filters contains unsupported keys"
    statuses = filters.get("statuses", [])
    protocols = filters.get("protocols", [])
    if not isinstance(statuses, list) or not set(statuses) <= _PROXY_STATUSES:
        return None, "proxy_filters.statuses contains an invalid status"
    if not isinstance(protocols, list) or not set(protocols) <= _PROXY_PROTOCOLS:
        return None, "proxy_filters.protocols contains an invalid protocol"
    normalized["proxy_filters"] = {
        "statuses": sorted(set(statuses)),
        "protocols": sorted(set(protocols)),
    }
    return normalized, None


def _privileged_role(role):
    return role in {"admin", "superadmin"}


def _json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def get_user_from_session():
    """Return the active user represented by the current browser session."""
    user_id = flask_session.get("user_id")
    if user_id is None:
        return None

    # The legacy environment-backed administrator is not stored in the DB.
    if user_id == 0:
        return {
            "id": 0,
            "username": flask_session.get("user", "admin"),
            "role": "admin",
            "custom_permissions": {},
            "is_active": True,
            "last_login": None,
        }

    with db.session() as db_session:
        user = (
            db_session.query(User)
            .filter_by(id=user_id, is_active=True)
            .first()
        )
        if not user:
            return None
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "custom_permissions": user.custom_permissions or {},
            "is_active": user.is_active,
            "last_login": user.last_login,
        }


@users_bp.route("/api/users/me", methods=["GET"])
@login_required
def api_current_user():
    user_data = get_user_from_session()
    if not user_data:
        return api_error("User not found", 404, "not_found")

    class UserStub:
        def __init__(self, data):
            self.id = data["id"]
            self.username = data["username"]
            self.role = data["role"]
            self.custom_permissions = data["custom_permissions"]
            self.is_active = data["is_active"]
            self.last_login = data["last_login"]

    user = UserStub(user_data)
    permissions = get_user_permissions(user)
    return jsonify(
        {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "permissions": sorted(permissions),
            "is_active": user.is_active,
            "last_login": user.last_login.isoformat() if user.last_login else None,
        }
    )


@users_bp.route("/api/users", methods=["GET"])
@login_required
@require_permission("users.manage")
def api_users_list():
    with db.session() as db_session:
        users = db_session.query(User).order_by(User.username.asc()).all()
        return jsonify([user.to_dict() for user in users])


@users_bp.route("/api/users", methods=["POST"])
@login_required
@require_permission("users.manage")
def api_users_create():
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    role = str(data.get("role", "user"))
    is_active = data.get("is_active", True)
    permissions, permissions_error = _normalize_custom_permissions(data.get("custom_permissions", {}))

    if not _USERNAME_RE.fullmatch(username):
        return api_error("Username must be 3-50 characters using letters, numbers, dot, dash, or underscore", 400, "invalid_username")
    if len(password) < 12:
        return api_error("Password must be at least 12 characters", 400, "weak_password")
    if role not in ROLE_PERMISSIONS:
        return api_error("Invalid role", 400, "invalid_role")
    if permissions_error:
        return api_error(permissions_error, 400, "invalid_permissions")
    if not isinstance(is_active, bool):
        return api_error("is_active must be a boolean", 400, "invalid_boolean")

    actor = get_user_from_session()
    if _privileged_role(role) and (not actor or not _privileged_role(actor["role"])):
        return api_error("Only an administrator can assign privileged roles", 403, "permission_denied")

    with db.session() as db_session:
        if db_session.query(User).filter_by(username=username).first():
            return api_error("Username already exists", 409, "duplicate_user")
        user = User(
            username=username,
            password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            role=role,
            custom_permissions=permissions,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.commit()
        return jsonify({"success": True, "id": user.id}), 201


@users_bp.route("/api/users/<int:user_id>", methods=["PUT"])
@login_required
@require_permission("users.manage")
def api_users_update(user_id):
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    if "role" in data and data["role"] not in ROLE_PERMISSIONS:
        return api_error("Invalid role", 400, "invalid_role")
    if "is_active" in data and not isinstance(data["is_active"], bool):
        return api_error("is_active must be a boolean", 400, "invalid_boolean")
    if data.get("password") and len(str(data["password"])) < 12:
        return api_error("Password must be at least 12 characters", 400, "weak_password")

    permissions = None
    if "custom_permissions" in data:
        permissions, permissions_error = _normalize_custom_permissions(data["custom_permissions"])
        if permissions_error:
            return api_error(permissions_error, 400, "invalid_permissions")

    actor = get_user_from_session()
    with db.session() as db_session:
        user = db_session.query(User).filter_by(id=user_id).first()
        if not user:
            return api_error("User not found", 404, "not_found")
        requested_role = data.get("role", user.role)
        if (_privileged_role(user.role) or _privileged_role(requested_role)) and (not actor or not _privileged_role(actor["role"])):
            return api_error("Only an administrator can modify privileged users", 403, "permission_denied")
        if user_id == flask_session.get("user_id") and data.get("is_active") is False:
            return api_error("Cannot deactivate yourself", 400, "self_lockout")

        if data.get("password"):
            user.password_hash = bcrypt.hashpw(str(data["password"]).encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            db_session.query(Token).filter_by(user_id=user_id).delete()
        if "role" in data:
            user.role = data["role"]
        if permissions is not None:
            user.custom_permissions = permissions
        if "is_active" in data:
            user.is_active = data["is_active"]
            if not user.is_active:
                db_session.query(Token).filter_by(user_id=user_id).delete()
        db_session.commit()
        return jsonify({"success": True})


@users_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@login_required
@require_permission("users.manage")
def api_users_delete(user_id):
    if user_id == flask_session.get("user_id"):
        return api_error("Cannot delete yourself", 400, "self_lockout")

    actor = get_user_from_session()
    with db.session() as db_session:
        user = db_session.query(User).filter_by(id=user_id).first()
        if not user:
            return api_error("User not found", 404, "not_found")
        if _privileged_role(user.role) and (not actor or not _privileged_role(actor["role"])):
            return api_error("Only an administrator can delete privileged users", 403, "permission_denied")
        db_session.query(Token).filter_by(user_id=user_id).delete()
        db_session.delete(user)
        db_session.commit()
        return jsonify({"success": True})


@users_bp.route("/api/users/permissions", methods=["GET"])
@login_required
@require_permission("users.manage")
def api_permissions_list():
    return jsonify(
        {
            "roles": list(ROLE_PERMISSIONS.keys()),
            "role_permissions": ROLE_PERMISSIONS,
            "all_permissions": ALL_PERMISSIONS,
        }
    )
