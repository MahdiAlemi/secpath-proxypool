import json
import os
import subprocess
import tempfile
import shutil
import glob
import sqlite3
import time
from datetime import datetime
from flask import Blueprint, current_app, request, jsonify, send_file, g, session as flask_session

from dashboard.decorators import login_required, require_permission
from dashboard.security import api_error
from dashboard.config import USERS
from backup_utils import (
    create_sqlite_backup,
    replace_sqlite_database,
    reserve_private_file,
    stage_sqlite_copy,
    validate_sqlite_database,
)

settings_bp = Blueprint('settings', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_json_object(path):
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _recent_start_reservation(payload, ttl=30.0):
    if payload.get("state") != "starting":
        return False
    try:
        return time.time() - float(payload.get("reserved_at_epoch", 0)) < float(ttl)
    except (TypeError, ValueError):
        return False


def _inspect_runtime_processes():
    """Inspect owned runtime processes without creating runtime directories."""
    from dashboard.config import load_monitors_config, load_servers_config
    from proxy_monitor.lifecycle import process_matches as monitor_process_matches
    from proxy_monitor.lifecycle import validate_monitor_id
    from proxy_server.lifecycle import process_matches as server_process_matches
    from proxy_server.lifecycle import validate_server_id

    active_monitors = []
    active_servers = []
    invalid_monitors = []
    invalid_servers = []

    monitor_registry = load_monitors_config()
    monitor_records = monitor_registry if isinstance(monitor_registry, dict) else {}
    monitor_ids = {str(item) for item in monitor_records}
    monitor_runtime = os.path.join(BASE_DIR, ".runtime", "monitors")
    for path in glob.glob(os.path.join(monitor_runtime, "*.claim.json")):
        name = os.path.basename(path)
        monitor_ids.add(name[: -len(".claim.json")])

    for raw_id in sorted(monitor_ids):
        try:
            monitor_id = validate_monitor_id(raw_id)
        except (TypeError, ValueError):
            invalid_monitors.append(raw_id)
            continue
        record = monitor_records.get(raw_id, monitor_records.get(monitor_id, {}))
        if not isinstance(record, dict):
            invalid_monitors.append(monitor_id)
            continue
        running = monitor_process_matches(
            record.get("pid"),
            monitor_id,
            expected_create_time=record.get("process_create_time"),
        )
        claim = _read_json_object(os.path.join(monitor_runtime, f"{monitor_id}.claim.json"))
        if not running and claim:
            running = monitor_process_matches(
                claim.get("pid"),
                monitor_id,
                expected_create_time=claim.get("process_create_time"),
            )
        if running or _recent_start_reservation(claim):
            active_monitors.append(monitor_id)

    server_registry = load_servers_config()
    server_records = server_registry if isinstance(server_registry, dict) else {}
    server_ids = {str(item) for item in server_records}
    server_runtime = os.path.join(BASE_DIR, ".runtime", "servers")
    for path in glob.glob(os.path.join(server_runtime, "*.json")):
        name = os.path.basename(path)
        if name.endswith(".profile.json"):
            continue
        server_ids.add(name[:-len(".json")])

    for raw_id in sorted(server_ids):
        try:
            server_id = validate_server_id(raw_id)
        except (TypeError, ValueError):
            invalid_servers.append(raw_id)
            continue
        state = _read_json_object(os.path.join(server_runtime, f"{server_id}.json"))
        running = server_process_matches(
            state.get("pid"),
            server_id,
            expected_create_time=state.get("process_create_time"),
        )
        if running or _recent_start_reservation(state):
            active_servers.append(server_id)

    return {
        "monitors": active_monitors,
        "servers": active_servers,
        "invalid_monitors": invalid_monitors,
        "invalid_servers": invalid_servers,
        "monitor_profiles": len(monitor_records),
        "server_profiles": len(server_records),
    }


@settings_bp.route("/api/settings", methods=["GET"])
@login_required
@require_permission("settings.view")
def api_settings():
    from config import config
    db_type = config.DB_TYPE
    sqlite_db_path = config.SQLITE_DB_PATH
    sqlite_abs = sqlite_db_path if os.path.isabs(sqlite_db_path) else os.path.join(BASE_DIR, sqlite_db_path)
    return jsonify({
        "db_type": db_type,
        "db_name": os.getenv('DB_NAME', 'proxypool'),
        "sqlite_db_path": sqlite_db_path,
        "db_path": sqlite_abs,
        "db_size": (os.path.getsize(sqlite_abs) / 1024 / 1024) if os.path.exists(sqlite_abs) else 0,
        "users": list(USERS.keys())
    })


@settings_bp.route("/api/settings/diagnostics", methods=["GET"])
@login_required
@require_permission("settings.view")
def api_settings_diagnostics():
    """Return a bounded operational snapshot without exposing secrets."""
    from sqlalchemy import func, or_
    from config import config
    from database import db, Proxy, Token, User

    db_type = config.DB_TYPE.lower()
    sqlite_path = config.SQLITE_DB_PATH
    sqlite_abs = sqlite_path if os.path.isabs(sqlite_path) else os.path.join(BASE_DIR, sqlite_path)
    runtime_processes = _inspect_runtime_processes()

    progress_dir = os.path.join(BASE_DIR, "progress")
    progress_count = len(glob.glob(os.path.join(progress_dir, "*.json"))) if os.path.isdir(progress_dir) else 0
    runtime_dir = os.path.join(BASE_DIR, ".runtime")
    runtime_file_count = 0
    if os.path.isdir(runtime_dir):
        runtime_file_count = sum(len(files) for _root, _dirs, files in os.walk(runtime_dir))

    log_files = [path for path in glob.glob(os.path.join(BASE_DIR, "*.log")) if os.path.isfile(path)]
    backup_files = sorted(
        glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sql"))
        + glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sqlite")),
        reverse=True,
    )

    recommendations = []
    with db.session() as session:
        total = session.query(func.count(Proxy.id)).scalar() or 0
        alive = session.query(func.count(Proxy.id)).filter(Proxy.status == "alive").scalar() or 0
        soft = session.query(func.count(Proxy.id)).filter(Proxy.status == "soft").scalar() or 0
        dead = session.query(func.count(Proxy.id)).filter(Proxy.status == "dead").scalar() or 0
        revived = session.query(func.count(Proxy.id)).filter(Proxy.status == "revived").scalar() or 0
        untested = session.query(func.count(Proxy.id)).filter(or_(Proxy.status == "untested", Proxy.status.is_(None))).scalar() or 0
        web_ready = session.query(func.count(Proxy.id)).filter(Proxy.status == "alive", Proxy.web_https_ok.is_(True)).scalar() or 0
        dns_ready = session.query(func.count(Proxy.id)).filter(Proxy.status == "alive", Proxy.remote_dns_ok.is_(True)).scalar() or 0
        telegram_ready = session.query(func.count(Proxy.id)).filter(Proxy.status == "alive", Proxy.web_https_ok.is_(True), Proxy.telegram_ok.is_(True)).scalar() or 0
        full_capability = session.query(func.count(Proxy.id)).filter(Proxy.status == "alive", Proxy.web_https_ok.is_(True), Proxy.remote_dns_ok.is_(True), Proxy.telegram_ok.is_(True)).scalar() or 0
        legacy_revived = session.query(func.count(Proxy.id)).filter(
            Proxy.status == "revived",
            Proxy.web_https_ok.is_(False),
            Proxy.remote_dns_ok.is_(False),
            Proxy.telegram_ok.is_(False),
        ).scalar() or 0
        user_count = session.query(func.count(User.id)).scalar() or 0
        active_users = session.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
        active_tokens = session.query(func.count(Token.id)).scalar() or 0

    secret_state = {
        "flask_secret_configured": bool(os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY")),
        "jwt_secret_configured": bool(os.environ.get("JWT_SECRET")),
        "session_cookie_secure": bool(current_app.config.get("SESSION_COOKIE_SECURE")),
        "legacy_admin_configured": bool(USERS),
    }

    if db_type == "sqlite" and not os.path.exists(sqlite_abs):
        recommendations.append("SQLite database file is missing. Initialize the schema before normal use.")
    if not secret_state["flask_secret_configured"] or not secret_state["jwt_secret_configured"]:
        recommendations.append("Configure independent FLASK_SECRET_KEY and JWT_SECRET values in .env.")
    if secret_state["legacy_admin_configured"]:
        recommendations.append("A legacy environment-backed administrator is still enabled. Prefer a database administrator.")
    if legacy_revived > 0:
        recommendations.append("Normalize legacy revived rows, then run a validation profile.")
    if alive > 0 and web_ready < alive:
        recommendations.append("Some alive proxies are not HTTPS-ready. Use capability filters for real client traffic.")
    if total > 0 and alive == 0:
        recommendations.append("No alive proxies are available. Run validation after importing fresh sources.")
    if progress_count > 20 or runtime_file_count > 100:
        recommendations.append("Runtime state is accumulating. Stop active processes before using runtime cleanup.")
    if not backup_files:
        recommendations.append("No database backup is present. Create one before destructive maintenance.")
    if not recommendations:
        recommendations.append("Operational preflight is healthy. Continue periodic validation and backups.")

    return jsonify({
        "success": True,
        "db": {
            "type": db_type,
            "sqlite_path": sqlite_abs,
            "sqlite_exists": os.path.exists(sqlite_abs),
            "sqlite_size_mb": (os.path.getsize(sqlite_abs) / 1024 / 1024) if os.path.exists(sqlite_abs) else 0,
        },
        "counts": {
            "total": total,
            "alive": alive,
            "soft": soft,
            "dead": dead,
            "revived": revived,
            "untested": untested,
            "web_ready": web_ready,
            "dns_ready": dns_ready,
            "telegram_ready": telegram_ready,
            "full_capability": full_capability,
            "legacy_revived": legacy_revived,
        },
        "runtime": {
            "monitor_profiles": runtime_processes["monitor_profiles"],
            "running_monitors": len(runtime_processes["monitors"]),
            "server_profiles": runtime_processes["server_profiles"],
            "running_servers": len(runtime_processes["servers"]),
            "invalid_monitor_profiles": len(runtime_processes["invalid_monitors"]),
            "invalid_server_profiles": len(runtime_processes["invalid_servers"]),
            "progress_files": progress_count,
            "runtime_files": runtime_file_count,
            "log_files": len(log_files),
            "log_size_mb": round(sum(os.path.getsize(path) for path in log_files) / 1024 / 1024, 3),
        },
        "backups": {
            "count": len(backup_files),
            "size_mb": round(sum(os.path.getsize(path) for path in backup_files) / 1024 / 1024, 3),
            "latest": os.path.basename(backup_files[0]) if backup_files else None,
        },
        "access": {
            "users": user_count,
            "active_users": active_users,
            "active_tokens": active_tokens,
        },
        "security": secret_state,
        "recommendations": recommendations,
    })


@settings_bp.route("/api/settings/password", methods=["POST"])
@login_required
@require_permission("settings.edit")
def api_settings_password():
    import bcrypt
    from database import Token, User, db

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("A JSON object is required", 400, "invalid_json")
    new_password = str(data.get("password", ""))
    if len(new_password) < 12:
        return api_error("Password must be at least 12 characters", 400, "weak_password")

    user_id = g.get("user_id", flask_session.get("user_id"))
    if not user_id:
        return api_error(
            "The environment-backed administrator cannot be changed at runtime; update DASHBOARD_PASSWORD or create a database administrator",
            409,
            "legacy_account",
        )

    with db.session() as db_session:
        user = db_session.query(User).filter_by(id=user_id, is_active=True).first()
        if not user:
            return api_error("User not found", 404, "not_found")
        user.password_hash = bcrypt.hashpw(
            new_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        db_session.query(Token).filter_by(user_id=user_id).delete()
        db_session.commit()
    return jsonify({"success": True})


@settings_bp.route("/api/settings/backup", methods=["POST"])
@login_required
@require_permission("settings.edit")
def api_settings_backup():
    from config import config

    db_type = config.DB_TYPE.lower()
    try:
        if db_type == 'sqlite':
            sqlite_path = config.SQLITE_DB_PATH
            if not os.path.isabs(sqlite_path):
                sqlite_path = os.path.join(BASE_DIR, sqlite_path)
            if not os.path.exists(sqlite_path):
                return api_error("SQLite database file was not found", 404, "not_found")
            backup_path = create_sqlite_backup(sqlite_path, directory=BASE_DIR)
        else:
            db_name = os.getenv('DB_NAME', 'proxypool')
            db_user = os.getenv('DB_USER', 'proxypool')
            db_pass = os.getenv('DB_PASS', '')
            db_host = os.getenv('DB_HOST', 'localhost')
            backup_path, backup_fd = reserve_private_file(
                BASE_DIR,
                prefix="proxies_backup",
                suffix=".sql",
            )
            cmd = ['mysqldump', f'-h{db_host}', f'-u{db_user}', db_name]
            env = os.environ.copy()
            if db_pass:
                # Avoid leaking the DB password via process argv (`ps`).
                env['MYSQL_PWD'] = db_pass
            try:
                with os.fdopen(backup_fd, 'w', encoding='utf-8') as output:
                    subprocess.run(cmd, stdout=output, check=True, env=env)
            except Exception:
                backup_path.unlink(missing_ok=True)
                raise

        return jsonify({
            "success": True,
            "file": backup_path.name,
            "size_mb": backup_path.stat().st_size / 1024 / 1024
        })
    except subprocess.CalledProcessError:
        current_app.logger.exception("Database backup command failed")
        return api_error("Database backup failed", 500, "backup_failed")
    except Exception:
        current_app.logger.exception("Database backup failed")
        return api_error("Database backup failed", 500, "backup_failed")


@settings_bp.route("/api/settings/backup/download", methods=["GET"])
@login_required
@require_permission("settings.edit", "proxies.credentials")
def api_settings_backup_download():
    backups = sorted(glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sql")) + glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sqlite")), reverse=True)
    if not backups:
        return api_error("No backups found", 404, "not_found")

    latest = backups[0]
    return send_file(latest, as_attachment=True, download_name=os.path.basename(latest))


@settings_bp.route("/api/settings/backups", methods=["GET"])
@login_required
@require_permission("settings.view")
def api_settings_backups():
    backups = sorted(glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sql")) + glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sqlite")), reverse=True)
    result = []
    for b in backups:
        result.append({
            "name": os.path.basename(b),
            "size_mb": os.path.getsize(b) / 1024 / 1024,
            "created": datetime.fromtimestamp(os.path.getctime(b)).strftime('%Y-%m-%d %H:%M:%S')
        })
    return jsonify({"backups": result})


@settings_bp.route("/api/settings/backups/<path:name>", methods=["GET"])
@login_required
@require_permission("settings.edit", "proxies.credentials")
def api_settings_backup_download_named(name):
    safe_name = os.path.basename(str(name or ""))
    if safe_name != name or not safe_name.startswith("proxies_backup_") or not safe_name.endswith((".sqlite", ".sql")):
        return api_error("Invalid backup name", 400, "invalid_backup_name")
    path = os.path.join(BASE_DIR, safe_name)
    if not os.path.isfile(path):
        return api_error("Backup not found", 404, "not_found")
    return send_file(path, as_attachment=True, download_name=safe_name)


@settings_bp.route("/api/settings/import", methods=["POST"])
@login_required
@require_permission("settings.edit", "proxies.credentials")
def api_settings_import():
    from config import config

    db_type = config.DB_TYPE.lower()
    mode = request.form.get("mode", "append")
    if mode not in {"append", "replace"}:
        return api_error("mode must be append or replace", 400, "invalid_mode")

    if "file" not in request.files:
        return api_error("No file provided", 400, "missing_file")

    file = request.files['file']
    filename = (file.filename or "").lower()

    try:
        if db_type == 'sqlite':
            # For SQLite, only full DB-file replacement is supported. This avoids executing arbitrary SQL uploads.
            if not filename.endswith('.sqlite'):
                return api_error("SQLite import only accepts .sqlite backup files", 400, "invalid_backup")
            if mode != "replace":
                return api_error("SQLite import supports replace mode only", 400, "invalid_mode")
            sqlite_path = config.SQLITE_DB_PATH
            if not os.path.isabs(sqlite_path):
                sqlite_path = os.path.join(BASE_DIR, sqlite_path)
            upload_path = None
            replacement_path = None
            previous_backup = None
            with tempfile.NamedTemporaryFile(dir=BASE_DIR, suffix=".sqlite", delete=False) as upload:
                upload_path = upload.name
            try:
                file.save(upload_path)
                validate_sqlite_database(upload_path)
                if os.path.exists(sqlite_path):
                    previous_backup = create_sqlite_backup(
                        sqlite_path,
                        directory=BASE_DIR,
                        prefix="proxies_backup_before_import",
                    )
                replacement_path = stage_sqlite_copy(
                    upload_path,
                    destination_directory=os.path.dirname(sqlite_path) or BASE_DIR,
                )
                from database import db, ensure_db_schema
                if getattr(db, "Session", None) is not None:
                    db.Session.remove()
                if getattr(db, "engine", None) is not None:
                    db.engine.dispose()
                replace_sqlite_database(replacement_path, sqlite_path)
                replacement_path = None
                try:
                    ensure_db_schema()
                except Exception:
                    current_app.logger.exception("Restored SQLite database failed schema initialization; rolling back")
                    if previous_backup is not None:
                        rollback_path = stage_sqlite_copy(
                            previous_backup,
                            destination_directory=os.path.dirname(sqlite_path) or BASE_DIR,
                        )
                        replace_sqlite_database(rollback_path, sqlite_path)
                        ensure_db_schema()
                    raise
            finally:
                if upload_path and os.path.exists(upload_path):
                    os.unlink(upload_path)
                if replacement_path and os.path.exists(replacement_path):
                    os.unlink(replacement_path)
            return jsonify({
                "success": True,
                "mode": mode,
                "backup": previous_backup.name if previous_backup else None,
            })

        if not filename.endswith('.sql'):
            return api_error("MySQL import only accepts .sql files", 400, "invalid_backup")

        db_name = os.getenv('DB_NAME', 'proxypool')
        db_user = os.getenv('DB_USER', 'proxypool')
        db_pass = os.getenv('DB_PASS', '')
        db_host = os.getenv('DB_HOST', 'localhost')
        env = os.environ.copy()
        if db_pass:
            env['MYSQL_PWD'] = db_pass

        backup_path, backup_fd = reserve_private_file(
            BASE_DIR,
            prefix="proxies_backup_before_import",
            suffix=".sql",
        )
        try:
            with os.fdopen(backup_fd, 'w', encoding='utf-8') as backup_file:
                subprocess.run(
                    ['mysqldump', f'-h{db_host}', f'-u{db_user}', db_name],
                    stdout=backup_file,
                    check=True,
                    env=env,
                )
        except Exception:
            backup_path.unlink(missing_ok=True)
            raise

        if mode == "replace":
            subprocess.run([
                'mysql', f'-h{db_host}', f'-u{db_user}', db_name,
                '-e', 'SET FOREIGN_KEY_CHECKS=0; TRUNCATE TABLE proxies; SET FOREIGN_KEY_CHECKS=1;'
            ], check=True, stderr=subprocess.DEVNULL, env=env)

        with tempfile.NamedTemporaryFile(mode='wb', suffix='.sql', delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        try:
            with open(tmp_path, 'r') as sql_in:
                result = subprocess.run(
                    ['mysql', f'-h{db_host}', f'-u{db_user}', db_name],
                    stdin=sql_in,
                    capture_output=True,
                    text=True,
                    env=env
                )
            if result.returncode != 0:
                current_app.logger.error("MySQL import failed: %s", result.stderr[-2000:])
                return api_error("Database import failed", 500, "database_import_failed")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return jsonify({"success": True, "mode": mode, "backup": backup_path.name})

    except (ValueError, sqlite3.DatabaseError) as exc:
        return api_error(str(exc), 400, "invalid_backup")
    except subprocess.CalledProcessError:
        current_app.logger.exception("Database import command failed")
        return api_error("Database import failed", 500, "database_import_failed")
    except Exception:
        current_app.logger.exception("Database import failed")
        return api_error("Database import failed", 500, "database_import_failed")




@settings_bp.route("/api/settings/cleanup/logs", methods=["POST"])
@login_required
@require_permission("settings.edit")
def api_settings_cleanup_logs():
    """Delete runtime log files from the project root."""
    patterns = ["dashboard.log", "server_*.log", "monitor_*.log", "*.log"]
    deleted = 0
    files = set()
    for pattern in patterns:
        files.update(glob.glob(os.path.join(BASE_DIR, pattern)))
    for path in files:
        if not os.path.isfile(path):
            continue
        # Keep cleanup conservative: only files directly under project root.
        if os.path.dirname(os.path.abspath(path)) != os.path.abspath(BASE_DIR):
            continue
        try:
            os.remove(path)
            deleted += 1
        except OSError:
            pass
    return jsonify({"success": True, "deleted": deleted})


@settings_bp.route("/api/settings/cleanup/runtime", methods=["POST"])
@login_required
@require_permission("settings.edit")
def api_settings_cleanup_runtime():
    """Clear stale runtime state only when no owned process is active."""
    runtime_processes = _inspect_runtime_processes()
    invalid = {
        "monitors": runtime_processes["invalid_monitors"],
        "servers": runtime_processes["invalid_servers"],
    }
    if invalid["monitors"] or invalid["servers"]:
        return jsonify({
            "success": False,
            "error": "Runtime registry contains invalid profile identifiers; repair it before cleanup",
            "code": "runtime_registry_invalid",
            "invalid": invalid,
        }), 409
    if runtime_processes["monitors"] or runtime_processes["servers"]:
        return jsonify({
            "success": False,
            "error": "Stop active monitors and servers before clearing runtime state",
            "code": "runtime_active",
            "active": {
                "monitors": runtime_processes["monitors"],
                "servers": runtime_processes["servers"],
            },
        }), 409

    deleted = 0
    for name in [".monitor.pid", ".server.pid"]:
        path = os.path.join(BASE_DIR, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
                deleted += 1
            except OSError:
                pass
    for directory in [os.path.join(BASE_DIR, "progress"), os.path.join(BASE_DIR, ".runtime")]:
        if os.path.isdir(directory):
            try:
                shutil.rmtree(directory)
                deleted += 1
            except OSError:
                pass
    return jsonify({"success": True, "deleted": deleted})


@settings_bp.route("/api/settings/cleanup/legacy-statuses", methods=["POST"])
@login_required
@require_permission("settings.edit")
def api_settings_cleanup_legacy_statuses():
    """Normalize legacy statuses produced before the state-machine fix."""
    from database import db, Proxy
    with db.session() as session:
        # Old bug: untested failures became revived. If a revived proxy has never
        # succeeded, normalize it to dead.
        revived_to_dead = session.query(Proxy).filter(
            Proxy.status == 'revived',
            (Proxy.alive_hits.is_(None)) | (Proxy.alive_hits == 0)
        ).update({Proxy.status: 'dead'}, synchronize_session=False)

        # If revived has successes but is not currently confirmed alive, keep it
        # as soft so a normal monitor run can promote/demote it.
        revived_to_soft = session.query(Proxy).filter(
            Proxy.status == 'revived',
            Proxy.alive_hits > 0
        ).update({Proxy.status: 'soft'}, synchronize_session=False)

        # Clear obviously stale transition labels after normalization.
        session.commit()
    return jsonify({
        "success": True,
        "revived_to_dead": revived_to_dead,
        "revived_to_soft": revived_to_soft,
        "updated": revived_to_dead + revived_to_soft
    })
