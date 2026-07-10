#!/usr/bin/env python3
"""Create or update a database-backed ProxyPool administrator."""
from __future__ import annotations

import argparse
import getpass
import re
import sys
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import User, db, ensure_db_schema  # noqa: E402

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--role", choices=["admin", "superadmin"], default="admin")
    parser.add_argument("--update", action="store_true", help="Update an existing user")
    args = parser.parse_args()

    if not USERNAME_RE.fullmatch(args.username):
        parser.error("username must be 3-50 characters using letters, numbers, dot, dash, or underscore")

    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("Password must be at least 12 characters", file=sys.stderr)
        return 2

    ensure_db_schema()
    with db.session() as session:
        user = session.query(User).filter_by(username=args.username).first()
        if user and not args.update:
            print("User already exists. Re-run with --update to replace its password/role.", file=sys.stderr)
            return 3
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        if user:
            user.password_hash = password_hash
            user.role = args.role
            user.is_active = True
            action = "updated"
        else:
            session.add(
                User(
                    username=args.username,
                    password_hash=password_hash,
                    role=args.role,
                    custom_permissions={},
                    is_active=True,
                )
            )
            action = "created"
        session.commit()
    print(f"Database administrator '{args.username}' {action}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
