import bcrypt
from flask import Blueprint, jsonify, request, session as flask_session

from dashboard.config import ALL_PERMISSIONS, ROLE_PERMISSIONS
from dashboard.decorators import (
    get_user_permissions,
    login_required,
    require_permission,
)
from database import Token, User, db

users_bp = Blueprint("users", __name__)


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
        return jsonify({"error": "User not found"}), 404

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
        return jsonify({"error": "A JSON object is required"}), 400

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    role = str(data.get("role", "user"))
    custom_permissions = data.get("custom_permissions", {})
    is_active = data.get("is_active", True)

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if role not in ROLE_PERMISSIONS:
        return jsonify({"error": "Invalid role"}), 400
    if not isinstance(custom_permissions, dict):
        return jsonify({"error": "custom_permissions must be an object"}), 400
    if not isinstance(is_active, bool):
        return jsonify({"error": "is_active must be a boolean"}), 400

    with db.session() as db_session:
        if db_session.query(User).filter_by(username=username).first():
            return jsonify({"error": "Username already exists"}), 409

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        user = User(
            username=username,
            password_hash=password_hash,
            role=role,
            custom_permissions=custom_permissions,
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
        return jsonify({"error": "A JSON object is required"}), 400

    if "role" in data and data["role"] not in ROLE_PERMISSIONS:
        return jsonify({"error": "Invalid role"}), 400
    if "custom_permissions" in data and not isinstance(
        data["custom_permissions"], dict
    ):
        return jsonify({"error": "custom_permissions must be an object"}), 400
    if "is_active" in data and not isinstance(data["is_active"], bool):
        return jsonify({"error": "is_active must be a boolean"}), 400

    with db.session() as db_session:
        user = db_session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        if data.get("password"):
            user.password_hash = bcrypt.hashpw(
                str(data["password"]).encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
        if "role" in data:
            user.role = data["role"]
        if "custom_permissions" in data:
            user.custom_permissions = data["custom_permissions"]
        if "is_active" in data:
            user.is_active = data["is_active"]

        db_session.commit()
        return jsonify({"success": True})


@users_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@login_required
@require_permission("users.manage")
def api_users_delete(user_id):
    # Check the Flask session before opening a SQLAlchemy session. Previously,
    # both objects were named ``session``, causing this endpoint to crash.
    if user_id == flask_session.get("user_id"):
        return jsonify({"error": "Cannot delete yourself"}), 400

    with db.session() as db_session:
        user = db_session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

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
