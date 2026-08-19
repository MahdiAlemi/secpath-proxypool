from __future__ import annotations

from typing import Any

from sqlalchemy import func


SENSITIVE_FIELDS = {
    "password",
    "password_hash",
    "hashed_password",
    "token",
    "api_token",
    "secret",
    "jwt_secret",
}


def _model():
    try:
        from database import User
    except ImportError as exc:
        raise RuntimeError("This database schema does not expose a User model") from exc
    return User


def _columns() -> set[str]:
    User = _model()
    return {column.name for column in User.__table__.columns}


def schema() -> dict[str, Any]:
    User = _model()
    columns = []
    for column in User.__table__.columns:
        item = {
            "name": column.name,
            "type": str(column.type),
            "nullable": bool(column.nullable),
            "primary_key": bool(column.primary_key),
        }
        enum_values = getattr(column.type, "enums", None)
        if enum_values:
            item["choices"] = list(enum_values)
        columns.append(item)
    return {
        "model": "User",
        "table": User.__tablename__,
        "columns": columns,
        "password_setter": bool(hasattr(User, "set_password")),
    }


def _serialize(user) -> dict[str, Any]:
    data = {}
    for column in user.__table__.columns:
        name = column.name
        if name.lower() in SENSITIVE_FIELDS or "secret" in name.lower() or "password" in name.lower():
            continue
        data[name] = getattr(user, name, None)
    return data


def _username_column():
    User = _model()
    for name in ("username", "email", "name"):
        if hasattr(User, name):
            return getattr(User, name), name
    raise RuntimeError("Could not determine User identity column")


def _lookup(session, identifier: str):
    User = _model()
    identity_col, _ = _username_column()
    value = str(identifier).strip()
    if value.isdigit() and hasattr(User, "id"):
        row = session.query(User).filter(User.id == int(value)).first()
        if row is not None:
            return row
    return session.query(User).filter(func.lower(identity_col) == value.lower()).first()


def list_users() -> list[dict[str, Any]]:
    from database import db
    User = _model()
    identity_col, _ = _username_column()
    with db.session() as session:
        rows = session.query(User).order_by(identity_col.asc()).all()
        return [_serialize(row) for row in rows]


def get_user(identifier: str) -> dict[str, Any] | None:
    from database import db
    with db.session() as session:
        row = _lookup(session, identifier)
        return _serialize(row) if row is not None else None


def _set_password(user, password: str) -> None:
    encoded = password.encode("utf-8")
    if len(encoded) < 10:
        raise ValueError("Password must be at least 10 bytes")
    if len(encoded) > 72:
        raise ValueError("Password must be at most 72 UTF-8 bytes for bcrypt compatibility")
    setter = getattr(user, "set_password", None)
    if callable(setter):
        setter(password)
        return

    columns = _columns()
    if "password_hash" in columns:
        import bcrypt
        user.password_hash = bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")
        return
    if "hashed_password" in columns:
        import bcrypt
        user.hashed_password = bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")
        return
    raise RuntimeError("User model has no supported password setter/hash column")


def _validate_role(role: str | None) -> str | None:
    if role is None:
        return None
    User = _model()
    if not hasattr(User, "role"):
        raise RuntimeError("User model has no role field")
    from dashboard.config import ROLE_PERMISSIONS
    choices = tuple(ROLE_PERMISSIONS)
    value = role.strip().lower()
    if value not in choices:
        raise ValueError("Role must be one of: " + ", ".join(choices))
    return value


def create_user(*, username: str, password: str, role: str | None = None, active: bool = True) -> dict[str, Any]:
    from database import db
    User = _model()
    identity_col, identity_name = _username_column()
    clean = username.strip()
    if len(clean) < 2 or len(clean) > 255:
        raise ValueError("Username must contain 2 to 255 characters")
    clean_role = _validate_role(role)

    with db.session() as session:
        duplicate = session.query(User).filter(func.lower(identity_col) == clean.lower()).first()
        if duplicate is not None:
            raise RuntimeError(f"user {clean!r} already exists")
        user = User()
        setattr(user, identity_name, clean)
        if clean_role is not None and hasattr(user, "role"):
            user.role = clean_role
        if hasattr(user, "is_active"):
            user.is_active = bool(active)
        _set_password(user, password)
        session.add(user)
        session.flush()
        return _serialize(user)


def set_active(identifier: str, active: bool) -> dict[str, Any] | None:
    from database import db
    with db.session() as session:
        user = _lookup(session, identifier)
        if user is None:
            return None
        if not hasattr(user, "is_active"):
            raise RuntimeError("User model has no is_active field")
        user.is_active = bool(active)
        session.flush()
        return _serialize(user)


def set_role(identifier: str, role: str) -> dict[str, Any] | None:
    from database import db
    clean_role = _validate_role(role)
    with db.session() as session:
        user = _lookup(session, identifier)
        if user is None:
            return None
        user.role = clean_role
        session.flush()
        return _serialize(user)


def set_password(identifier: str, password: str) -> dict[str, Any] | None:
    from database import db
    with db.session() as session:
        user = _lookup(session, identifier)
        if user is None:
            return None
        _set_password(user, password)
        session.flush()
        return _serialize(user)


def delete_user(identifier: str) -> dict[str, Any] | None:
    from database import db
    User = _model()
    with db.session() as session:
        user = _lookup(session, identifier)
        if user is None:
            return None
        count = session.query(User).count()
        if count <= 1:
            raise RuntimeError("Refusing to delete the last user")
        result = _serialize(user)
        session.delete(user)
        return result
