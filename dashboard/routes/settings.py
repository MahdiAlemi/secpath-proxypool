import os
import subprocess
import tempfile
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file

from dashboard.decorators import login_required, require_permission
from dashboard.config import USERS

settings_bp = Blueprint('settings', __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@settings_bp.route("/api/settings", methods=["GET"])
@login_required
@require_permission("settings.view")
def api_settings():
    return jsonify({
        "db_type": "mysql",
        "db_name": os.getenv('DB_NAME', 'proxypool'),
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
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Password required"})


@settings_bp.route("/api/settings/backup", methods=["POST"])
@login_required
@require_permission("settings.edit")
def api_settings_backup():
    from config import config
    
    db_name = os.getenv('DB_NAME', 'proxypool')
    db_user = os.getenv('DB_USER', 'proxypool')
    db_pass = os.getenv('DB_PASS', '')
    db_host = os.getenv('DB_HOST', 'localhost')
    
    backup_name = os.path.join(BASE_DIR, f"proxies_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql")
    
    try:
        cmd = [
            'mysqldump',
            f'-h{db_host}',
            f'-u{db_user}',
            f'-p{db_pass}',
            db_name
        ]
        
        with open(backup_name, 'w') as f:
            subprocess.run(cmd, stdout=f, check=True)
        
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
    
    backups = sorted(glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sql")), reverse=True)
    if not backups:
        return jsonify({"success": False, "error": "No backups found"})
    
    latest = backups[0]
    return send_file(latest, as_attachment=True, download_name=os.path.basename(latest))


@settings_bp.route("/api/settings/backups", methods=["GET"])
@login_required
@require_permission("settings.view")
def api_settings_backups():
    import glob
    
    backups = sorted(glob.glob(os.path.join(BASE_DIR, "proxies_backup_*.sql")), reverse=True)
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
    db_name = os.getenv('DB_NAME', 'proxypool')
    db_user = os.getenv('DB_USER', 'proxypool')
    db_pass = os.getenv('DB_PASS', '')
    db_host = os.getenv('DB_HOST', 'localhost')
    
    mode = request.form.get("mode", "append")
    
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file provided"})
    
    file = request.files['file']
    if not file.filename or not file.filename.endswith('.sql'):
        return jsonify({"success": False, "error": "Only .sql files allowed"})
    
    try:
        backup_name = os.path.join(BASE_DIR, f"proxies_backup_before_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql")
        subprocess.run([
            'mysqldump', f'-h{db_host}', f'-u{db_user}', f'-p{db_pass}', db_name
        ], stdout=open(backup_name, 'w'), check=True)
        
        if mode == "replace":
            subprocess.run([
                'mysql', f'-h{db_host}', f'-u{db_user}', f'-p{db_pass}', db_name,
                '-e', 'SET FOREIGN_KEY_CHECKS=0; TRUNCATE TABLE proxies; SET FOREIGN_KEY_CHECKS=1;'
            ], check=True, stderr=subprocess.DEVNULL)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as tmp:
            file.save(tmp.name)
            tmp.flush()
            
            result = subprocess.run(
                ['mysql', f'-h{db_host}', f'-u{db_user}', f'-p{db_pass}', db_name],
                stdin=open(tmp.name, 'r'),
                capture_output=True,
                text=True
            )
            os.unlink(tmp.name)
            
            if result.returncode != 0:
                return jsonify({"success": False, "error": f"Import failed: {result.stderr}"})
        
        return jsonify({"success": True, "mode": mode})
        
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "error": f"Import failed: {str(e)}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
