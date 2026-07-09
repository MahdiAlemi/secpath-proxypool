import os
import subprocess
import tempfile
import shutil
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file

from dashboard.decorators import login_required, require_permission
from dashboard.config import USERS

settings_bp = Blueprint('settings', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@settings_bp.route("/api/settings", methods=["GET"])
@login_required
@require_permission("settings.view")
def api_settings():
    return jsonify({
        "db_type": os.getenv('DB_TYPE', 'mysql'),
        "db_name": os.getenv('DB_NAME', 'proxypool'),
        "sqlite_db_path": os.getenv('SQLITE_DB_PATH', 'proxies.db'),
        "users": list(USERS.keys())
    })


@settings_bp.route("/api/settings/password", methods=["POST"])
@login_required
@require_permission("settings.edit")
def api_settings_password():
    from dashboard.config import USERS
    data = request.json
    new_pass = data.get("password", "")
    if new_pass:
        USERS["admin"] = new_pass
        return jsonify({"success": True, "warning": "Password changed for this running process only. Set DASHBOARD_PASSWORD in .env for persistence."})
    return jsonify({"success": False, "error": "Password required"})


@settings_bp.route("/api/settings/backup", methods=["POST"])
@login_required
@require_permission("settings.edit")
def api_settings_backup():
    from config import config

    db_type = os.getenv('DB_TYPE', 'mysql').lower()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    try:
        if db_type == 'sqlite':
            sqlite_path = config.SQLITE_DB_PATH
            if not os.path.isabs(sqlite_path):
                sqlite_path = os.path.join(BASE_DIR, sqlite_path)
            if not os.path.exists(sqlite_path):
                return jsonify({"success": False, "error": f"SQLite DB not found: {sqlite_path}"})
            backup_name = os.path.join(BASE_DIR, f"proxies_backup_{timestamp}.sqlite")
            shutil.copy2(sqlite_path, backup_name)
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
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "error": f"Backup failed: {str(e)}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@settings_bp.route("/api/settings/backup/download", methods=["GET"])
@login_required
@require_permission("settings.view")
def api_settings_backup_download():
    import glob
    
    backups = sorted(glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sql")) + glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sqlite")), reverse=True)
    if not backups:
        return jsonify({"success": False, "error": "No backups found"})
    
    latest = backups[0]
    return send_file(latest, as_attachment=True, download_name=os.path.basename(latest))


@settings_bp.route("/api/settings/backups", methods=["GET"])
@login_required
@require_permission("settings.view")
def api_settings_backups():
    import glob
    
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
@require_permission("settings.edit")
def api_settings_import():
    from config import config

    db_type = os.getenv('DB_TYPE', 'mysql').lower()
    mode = request.form.get("mode", "append")

    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file provided"})

    file = request.files['file']
    filename = file.filename or ''

    try:
        if db_type == 'sqlite':
            # For SQLite, only full DB-file replacement is supported. This avoids executing arbitrary SQL uploads.
            if not filename.endswith('.sqlite'):
                return jsonify({"success": False, "error": "SQLite import only accepts .sqlite backup files"})
            if mode != "replace":
                return jsonify({"success": False, "error": "SQLite import supports replace mode only"})
            sqlite_path = config.SQLITE_DB_PATH
            if not os.path.isabs(sqlite_path):
                sqlite_path = os.path.join(BASE_DIR, sqlite_path)
            backup_name = os.path.join(BASE_DIR, f"proxies_backup_before_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite")
            if os.path.exists(sqlite_path):
                shutil.copy2(sqlite_path, backup_name)
            file.save(sqlite_path)
            return jsonify({"success": True, "mode": mode, "backup": os.path.basename(backup_name)})

        if not filename.endswith('.sql'):
            return jsonify({"success": False, "error": "MySQL import only accepts .sql files"})

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
                return jsonify({"success": False, "error": f"Import failed: {result.stderr}"})
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return jsonify({"success": True, "mode": mode, "backup": os.path.basename(backup_name)})

    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "error": f"Import failed: {str(e)}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

