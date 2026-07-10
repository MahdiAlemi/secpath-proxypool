import os
import subprocess
import tempfile
import shutil
import glob
import sqlite3
from datetime import datetime
from flask import Blueprint, current_app, request, jsonify, send_file, g, session as flask_session

from dashboard.decorators import login_required, require_permission
from dashboard.security import api_error
from dashboard.config import USERS

settings_bp = Blueprint('settings', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _sqlite_backup(source_path, destination_path):
    """Create a transactionally consistent SQLite backup."""
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    destination = sqlite3.connect(destination_path)
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()


def _validate_sqlite_backup(path):
    if os.path.getsize(path) < 100 or os.path.getsize(path) > 512 * 1024 * 1024:
        raise ValueError("SQLite backup size is invalid")
    with open(path, "rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise ValueError("Uploaded file is not a SQLite database")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("SQLite backup failed integrity validation")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "proxies" not in tables:
            raise ValueError("SQLite backup does not contain the proxies table")
    finally:
        connection.close()


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
    """Return an operator-friendly health snapshot for local preflight checks."""
    from sqlalchemy import func, or_
    from config import config
    from database import db, Proxy

    db_type = config.DB_TYPE.lower()
    sqlite_path = config.SQLITE_DB_PATH
    sqlite_abs = sqlite_path if os.path.isabs(sqlite_path) else os.path.join(BASE_DIR, sqlite_path)

    runtime_files = []
    for name in [".monitors.json", ".servers.json", ".server_config.json", "dashboard/.monitors.json", "dashboard/.servers.json"]:
        path = os.path.join(BASE_DIR, name)
        runtime_files.append({"name": name, "exists": os.path.exists(path)})

    progress_dir = os.path.join(BASE_DIR, "progress")
    progress_count = len(glob.glob(os.path.join(progress_dir, "*.json"))) if os.path.isdir(progress_dir) else 0

    recommendations = []
    with db.session() as session:
        total = session.query(func.count(Proxy.id)).scalar() or 0
        alive = session.query(func.count(Proxy.id)).filter(Proxy.status == 'alive').scalar() or 0
        soft = session.query(func.count(Proxy.id)).filter(Proxy.status == 'soft').scalar() or 0
        dead = session.query(func.count(Proxy.id)).filter(Proxy.status == 'dead').scalar() or 0
        revived = session.query(func.count(Proxy.id)).filter(Proxy.status == 'revived').scalar() or 0
        untested = session.query(func.count(Proxy.id)).filter(or_(Proxy.status == 'untested', Proxy.status.is_(None))).scalar() or 0
        web_ready = session.query(func.count(Proxy.id)).filter(Proxy.status == 'alive', Proxy.web_https_ok.is_(True)).scalar() or 0
        dns_ready = session.query(func.count(Proxy.id)).filter(Proxy.status == 'alive', Proxy.remote_dns_ok.is_(True)).scalar() or 0
        telegram_ready = session.query(func.count(Proxy.id)).filter(Proxy.status == 'alive', Proxy.web_https_ok.is_(True), Proxy.telegram_ok.is_(True)).scalar() or 0
        full_capability = session.query(func.count(Proxy.id)).filter(Proxy.status == 'alive', Proxy.web_https_ok.is_(True), Proxy.remote_dns_ok.is_(True), Proxy.telegram_ok.is_(True)).scalar() or 0
        legacy_revived = session.query(func.count(Proxy.id)).filter(
            Proxy.status == 'revived',
            Proxy.web_https_ok.is_(False),
            Proxy.remote_dns_ok.is_(False),
            Proxy.telegram_ok.is_(False),
        ).scalar() or 0

    if db_type == 'sqlite' and not os.path.exists(sqlite_abs):
        recommendations.append('SQLite database file is missing; run dev_setup or init_db before using the dashboard.')
    if legacy_revived > 0:
        recommendations.append('Legacy revived rows still need cleanup: use Settings → Normalize Legacy Statuses, then run a monitor.')
    if alive > 0 and web_ready < alive:
        recommendations.append('Some alive proxies are not web-ready; use Web-ready filters/server preset for real browsing traffic.')
    if total > 0 and alive == 0:
        recommendations.append('No alive proxies currently available; run a monitor after importing fresh sources.')
    if progress_count > 20:
        recommendations.append('Many progress files are present; use Clear Runtime Files when no monitors are running.')
    if not recommendations:
        recommendations.append('Preflight looks good. Continue using capability filters and run monitor refreshes regularly.')

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
            "files": runtime_files,
            "progress_files": progress_count,
        },
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
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    try:
        if db_type == 'sqlite':
            sqlite_path = config.SQLITE_DB_PATH
            if not os.path.isabs(sqlite_path):
                sqlite_path = os.path.join(BASE_DIR, sqlite_path)
            if not os.path.exists(sqlite_path):
                return api_error("SQLite database file was not found", 404, "not_found")
            backup_name = os.path.join(BASE_DIR, f"proxies_backup_{timestamp}.sqlite")
            _sqlite_backup(sqlite_path, backup_name)
        else:
            db_name = os.getenv('DB_NAME', 'proxypool')
            db_user = os.getenv('DB_USER', 'proxypool')
            db_pass = os.getenv('DB_PASS', '')
            db_host = os.getenv('DB_HOST', 'localhost')
            backup_name = os.path.join(BASE_DIR, f"proxies_backup_{timestamp}.sql")
            cmd = ['mysqldump', f'-h{db_host}', f'-u{db_user}', db_name]
            env = os.environ.copy()
            if db_pass:
                # Avoid leaking the DB password via process argv (`ps`).
                env['MYSQL_PWD'] = db_pass
            with open(backup_name, 'w') as f:
                subprocess.run(cmd, stdout=f, check=True, env=env)

        return jsonify({
            "success": True,
            "file": os.path.basename(backup_name),
            "size_mb": os.path.getsize(backup_name) / 1024 / 1024
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
            backup_name = os.path.join(BASE_DIR, f"proxies_backup_before_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite")
            staged_path = None
            with tempfile.NamedTemporaryFile(dir=BASE_DIR, suffix=".sqlite", delete=False) as staged:
                staged_path = staged.name
            try:
                file.save(staged_path)
                _validate_sqlite_backup(staged_path)
                if os.path.exists(sqlite_path):
                    _sqlite_backup(sqlite_path, backup_name)
                from database import db, ensure_db_schema
                if getattr(db, "Session", None) is not None:
                    db.Session.remove()
                if getattr(db, "engine", None) is not None:
                    db.engine.dispose()
                os.replace(staged_path, sqlite_path)
                staged_path = None
                ensure_db_schema()
            finally:
                if staged_path and os.path.exists(staged_path):
                    os.unlink(staged_path)
            return jsonify({"success": True, "mode": mode, "backup": os.path.basename(backup_name)})

        if not filename.endswith('.sql'):
            return api_error("MySQL import only accepts .sql files", 400, "invalid_backup")

        db_name = os.getenv('DB_NAME', 'proxypool')
        db_user = os.getenv('DB_USER', 'proxypool')
        db_pass = os.getenv('DB_PASS', '')
        db_host = os.getenv('DB_HOST', 'localhost')
        env = os.environ.copy()
        if db_pass:
            env['MYSQL_PWD'] = db_pass

        backup_name = os.path.join(BASE_DIR, f"proxies_backup_before_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql")
        with open(backup_name, 'w') as backup_file:
            subprocess.run(['mysqldump', f'-h{db_host}', f'-u{db_user}', db_name], stdout=backup_file, check=True, env=env)

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

        return jsonify({"success": True, "mode": mode, "backup": os.path.basename(backup_name)})

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
    """Clear stale runtime files without deleting the database."""
    deleted = 0
    for name in [".monitors.json", ".servers.json", ".monitor.pid", ".server.pid"]:
        path = os.path.join(BASE_DIR, name)
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted += 1
            except OSError:
                pass
    progress_dir = os.path.join(BASE_DIR, ".progress")
    if os.path.isdir(progress_dir):
        try:
            shutil.rmtree(progress_dir)
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
