import jwt
from functools import wraps
from datetime import datetime, timedelta, timezone
from flask import redirect, url_for, session, jsonify, g, request
from dashboard.config import ROLE_PERMISSIONS, ALL_PERMISSIONS, JWT_SECRET, JWT_EXPIRY_HOURS
from database import db, Token


def utcnow():
    """Return timezone-normalized UTC as naive datetime for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_token(user_id):
    """Create JWT token and store in database"""
    payload = {
        'user_id': user_id,
        'exp': utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        'iat': utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
    
    expires_at = payload['exp']
    with db.session() as db_session:
        token_record = Token(user_id=user_id, token=token, expires_at=expires_at)
        db_session.add(token_record)
        db_session.commit()
    
    return token


def validate_token(token_str):
    """Validate JWT token and return user_id"""
    try:
        payload = jwt.decode(token_str, JWT_SECRET, algorithms=['HS256'])
        user_id = payload.get('user_id')
        
        with db.session() as db_session:
            token_record = db_session.query(Token).filter_by(token=token_str).first()
            if not token_record:
                return None
            
            if token_record.expires_at < utcnow():
                db_session.delete(token_record)
                db_session.commit()
                return None
            
            from database import User
            user = db_session.query(User).filter_by(id=user_id, is_active=True).first()
            if user:
                return user_id
        
        return None
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def delete_token(token_str):
    """Delete token from database"""
    with db.session() as db_session:
        token_record = db_session.query(Token).filter_by(token=token_str).first()
        if token_record:
            db_session.delete(token_record)
            db_session.commit()


def delete_user_tokens(user_id):
    """Delete all tokens for a user"""
    with db.session() as db_session:
        db_session.query(Token).filter_by(user_id=user_id).delete()
        db_session.commit()


def cleanup_expired_tokens():
    """Remove expired tokens from database"""
    with db.session() as db_session:
        db_session.query(Token).filter(Token.expires_at < utcnow()).delete()
        db_session.commit()


def get_user_from_token():
    """Get user from JWT token in Authorization header"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    
    token = auth_header.split(' ')[1]
    user_id = validate_token(token)
    
    if not user_id:
        return None
    
    return user_id


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = None
        
        if 'user_id' in session:
            user_id = session.get('user_id')
        else:
            uid = get_user_from_token()
            if uid:
                user_id = uid
        
        if user_id is None:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for("login"))
        
        g.user_id = user_id
        return f(*args, **kwargs)
    return decorated


def get_user_permissions(user):
    """Get effective permissions for a user"""
    if user.role == 'admin' or user.role == 'superadmin' or '*' in ROLE_PERMISSIONS.get(user.role, []):
        return set(ALL_PERMISSIONS)
    
    perms = set(ROLE_PERMISSIONS.get(user.role, []))
    
    if user.custom_permissions:
        perms.update(user.custom_permissions.get('add', []))
        perms.difference_update(user.custom_permissions.get('remove', []))
    
    return perms


def get_user_proxy_filters(user):
    """
    Get proxy visibility filters for a user.
    Returns {"statuses": [], "protocols": []}
    - Admin/superadmin: empty arrays (no filter, see all)
    - Regular users: filtered based on custom_permissions
    """
    # Handle both User object and dict (for API responses)
    if isinstance(user, dict):
        role = user.get('role', 'user')
        custom_permissions = user.get('custom_permissions', {})
    else:
        # SQLAlchemy User object - access attributes before session closes
        role = user.role
        custom_permissions = user.custom_permissions
    
    # Admin sees all
    if role in ('admin', 'superadmin') or '*' in ROLE_PERMISSIONS.get(role, []):
        return {"statuses": [], "protocols": []}
    
    # Get filters from custom_permissions
    filters = custom_permissions.get('proxy_filters', {}) if custom_permissions else {}
    
    return {
        "statuses": filters.get('statuses', []),
        "protocols": filters.get('protocols', [])
    }


def is_admin(user):
    """Check if user is admin"""
    return user.role in ('admin', 'superadmin') or '*' in ROLE_PERMISSIONS.get(user.role, [])


def has_permission(permission):
    """Check if current user has specific permission"""
    user_id = g.get('user_id')
    if user_id is None:
        user_id = session.get('user_id')
    if user_id is None:
        return False
    if user_id == 0:
        return True
    
    from database import User
    with db.session() as db_session:
        user = db_session.query(User).filter_by(id=user_id, is_active=True).first()
        if not user:
            return False
        
        perms = get_user_permissions(user)
        return permission in perms or '*' in perms


def require_permission(*permissions):
    """Decorator to require specific permissions"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = g.get('user_id')
            if user_id is None:
                user_id = session.get('user_id')
            if user_id is None:
                if request.is_json:
                    return jsonify({'error': 'Authentication required'}), 401
                return redirect(url_for("login"))
            if user_id == 0:
                return f(*args, **kwargs)
            
            from database import User
            with db.session() as db_session:
                user = db_session.query(User).filter_by(id=user_id, is_active=True).first()
                if not user:
                    if request.is_json:
                        return jsonify({'error': 'User not found or inactive'}), 403
                    return redirect(url_for("login"))
                
                perms = get_user_permissions(user)
                
                for perm in permissions:
                    if perm not in perms and '*' not in perms:
                        if request.is_json:
                            return jsonify({'error': f'Permission denied: {perm}'}), 403
                        return redirect(url_for("index"))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_current_user():
    """Get current user object from session"""
    user_id = g.get('user_id')
    if user_id is None:
        user_id = session.get('user_id')
    if user_id is None:
        return None
    if user_id == 0:
        return {
            'id': 0,
            'username': session.get('user', 'admin'),
            'role': 'admin',
            'custom_permissions': {},
            'is_active': True
        }
    
    from database import User
    with db.session() as db_session:
        user = db_session.query(User).filter_by(id=user_id, is_active=True).first()
        if user:
            # Return dict with needed attributes to avoid detached instance error
            return {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'custom_permissions': user.custom_permissions,
                'is_active': user.is_active
            }
    return None
