from flask import Blueprint, request, jsonify, session
from dashboard.decorators import login_required, require_permission, get_user_permissions
from dashboard.config import ROLE_PERMISSIONS, ALL_PERMISSIONS
from database import db, User
import bcrypt

users_bp = Blueprint('users', __name__)


def get_user_from_session():
    """Get current user from Flask session"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    
    with db.session() as db_session:
        user = db_session.query(User).filter_by(id=user_id, is_active=True).first()
        if user:
            return {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'custom_permissions': user.custom_permissions,
                'is_active': user.is_active,
                'last_login': user.last_login
            }
    return None


@users_bp.route("/api/users/me", methods=["GET"])
@login_required
def api_current_user():
    user_data = get_user_from_session()
    if not user_data:
        return jsonify({"error": "User not found"}), 404
    
    class UserStub:
        def __init__(self, data):
            self.id = data['id']
            self.username = data['username']
            self.role = data['role']
            self.custom_permissions = data['custom_permissions']
            self.is_active = data['is_active']
            self.last_login = data['last_login']
    
    user = UserStub(user_data)
    perms = get_user_permissions(user)
    
    return jsonify({
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "permissions": list(perms),
        "is_active": user.is_active,
        "last_login": user.last_login.isoformat() if user.last_login else None
    })


@users_bp.route("/api/users", methods=["GET"])
@login_required
@require_permission("users.manage")
def api_users_list():
    with db.session() as session:
        users = session.query(User).all()
        result = []
        for u in users:
            result.append({
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "custom_permissions": u.custom_permissions,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login": u.last_login.isoformat() if u.last_login else None,
            })
        return jsonify(result)


@users_bp.route("/api/users", methods=["POST"])
@login_required
@require_permission("users.manage")
def api_users_create():
    data = request.json
    
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    custom_permissions = data.get("custom_permissions", {})
    is_active = data.get("is_active", True)
    
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    
    if role not in ROLE_PERMISSIONS:
        return jsonify({"error": "Invalid role"}), 400
    
    with db.session() as session:
        existing = session.query(User).filter_by(username=username).first()
        if existing:
            return jsonify({"error": "Username already exists"}), 400
        
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        user = User(
            username=username,
            password_hash=password_hash,
            role=role,
            custom_permissions=custom_permissions,
            is_active=is_active
        )
        session.add(user)
        session.commit()
        
        return jsonify({"success": True, "id": user.id})


@users_bp.route("/api/users/<int:user_id>", methods=["PUT"])
@login_required
@require_permission("users.manage")
def api_users_update(user_id):
    data = request.json
    
    with db.session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        if "password" in data and data["password"]:
            user.password_hash = bcrypt.hashpw(data["password"].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        if "role" in data:
            if data["role"] in ROLE_PERMISSIONS:
                user.role = data["role"]
        
        if "custom_permissions" in data:
            user.custom_permissions = data["custom_permissions"]
        
        if "is_active" in data:
            user.is_active = data["is_active"]
        
        session.commit()
        
        return jsonify({"success": True})


@users_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@login_required
@require_permission("users.manage")
def api_users_delete(user_id):
    with db.session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        if user.id == session.get('user_id'):
            return jsonify({"error": "Cannot delete yourself"}), 400
        
        session.delete(user)
        session.commit()
        
        return jsonify({"success": True})


@users_bp.route("/api/users/permissions", methods=["GET"])
@login_required
@require_permission("users.manage")
def api_permissions_list():
    return jsonify({
        "roles": list(ROLE_PERMISSIONS.keys()),
        "role_permissions": ROLE_PERMISSIONS,
        "all_permissions": ALL_PERMISSIONS
    })
