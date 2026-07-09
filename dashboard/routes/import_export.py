import os
import subprocess
import tempfile

from flask import Blueprint, request, jsonify

from dashboard.decorators import login_required, require_permission

import_export_bp = Blueprint('import_export', __name__)


def get_db():
    from flask import g
    if "db_session" not in g:
        from database import db
        g.db_session = db.get_session()
    return g.db_session


@import_export_bp.route("/api/import", methods=["POST"])
@login_required
@require_permission("proxies.import")
def api_import():
    from sqlalchemy import or_
    from database import Proxy
    
    mode = request.json.get("mode")
    session = get_db()

    result = {"success": True, "added": 0, "skipped": 0, "message": ""}

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    importer_path = os.path.join(base_dir, "proxy_importer", "app.py")

    if mode == "links":
        content = request.json.get("content", "")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
            f.write(content)
            temp_file = f.name
        try:
            proc = subprocess.run(
                ["python3", importer_path, "--mode", "links", "--file", temp_file],
                capture_output=True, text=True, timeout=120
            )
            output = proc.stdout + proc.stderr
            result["message"] = output
            # Parse added/skipped from importer output
            import re
            match = re.search(r'Added (\d+).*Skipped (\d+)', output)
            if match:
                result["added"] = int(match.group(1))
                result["skipped"] = int(match.group(2))
            else:
                # Try alternative format
                match = re.search(r'Added (\d+) new proxies', output)
                if match:
                    result["added"] = int(match.group(1))
        except Exception as e:
            result["success"] = False
            result["message"] = str(e)
        finally:
            os.unlink(temp_file)

    elif mode == "url":
        url = request.json.get("url")
        proto = request.json.get("protocol", "http")
        content = f"[{proto}]\n{url}"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
            f.write(content)
            temp_file = f.name
        try:
            proc = subprocess.run(
                ["python3", importer_path, "--mode", "links", "--file", temp_file],
                capture_output=True, text=True, timeout=60
            )
            output = proc.stdout
            result["message"] = output
            # Parse added/skipped from importer output
            import re
            match = re.search(r'Added (\d+).*Skipped (\d+)', output)
            if match:
                result["added"] = int(match.group(1))
                result["skipped"] = int(match.group(2))
            else:
                match = re.search(r'Added (\d+) new proxies', output)
                if match:
                    result["added"] = int(match.group(1))
        except Exception as e:
            result["success"] = False
            result["message"] = str(e)
        finally:
            os.unlink(temp_file)

    elif mode == "manual":
        proxies = request.json.get("proxies", "")
        lines = proxies.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                proto, ip, port = parts[0], parts[1], parts[2]
                user = parts[3] if len(parts) > 3 else ""
                pwd = parts[4] if len(parts) > 4 else ""
                try:
                    existing = session.query(Proxy).filter_by(
                        protocol=proto, ip=ip, port=int(port), username=user, password=pwd
                    ).first()
                    if not existing:
                        proxy = Proxy(protocol=proto, ip=ip, port=int(port), username=user, password=pwd, cost=1.0)
                        session.add(proxy)
                        result["added"] += 1
                except:
                    result["skipped"] += 1
        session.commit()

    return jsonify(result)


@import_export_bp.route("/api/import/count-url", methods=["POST"])
@login_required
@require_permission("proxies.import")
def api_import_count_url():
    """Count proxies in a URL without importing"""
    import requests
    
    url = request.json.get("url", "")
    proto = request.json.get("protocol", "http")
    
    if not url:
        return jsonify({"success": False, "error": "URL required", "count": 0})
    
    try:
        response = requests.get(url, timeout=30)
        content = response.text
        
        lines = content.strip().split("\n")
        count = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if proto in ['http', 'https']:
                if '://' in line or '.' in line:
                    count += 1
            else:
                if '://' in line or '.' in line:
                    count += 1
        
        return jsonify({"success": True, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "count": 0})


@import_export_bp.route("/api/export", methods=["GET"])
@login_required
@require_permission("proxies.export")
def api_export():
    from sqlalchemy import or_
    from database import Proxy
    
    fmt = request.args.get("format", "txt")
    cols_param = request.args.get("columns", "")
    proto = request.args.get("proto", "all")
    status = request.args.get("status", "all")
    search = request.args.get("search", "")
    ip_filter = request.args.get("ip", "")
    country_filter = request.args.get("country", "")
    isp_filter = request.args.get("isp", "")
    adv_search_json = request.args.get("adv_search", "[]")
    
    session = get_db()
    
    query = session.query(Proxy)
    
    if proto != "all":
        query = query.filter(Proxy.protocol == proto)
    
    if status != "all":
        if status == "untested":
            query = query.filter(or_(Proxy.status == 'untested', Proxy.status.is_(None)))
        else:
            query = query.filter(Proxy.status == status)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(
            Proxy.ip.like(search_term),
            Proxy.countryCode.like(search_term),
            Proxy.isp.like(search_term),
            Proxy.city.like(search_term),
            Proxy.regionName.like(search_term)
        ))
    
    if ip_filter:
        query = query.filter(Proxy.ip.like(f"%{ip_filter}%"))
    
    if country_filter:
        query = query.filter(Proxy.countryCode.like(f"%{country_filter}%"))
    
    if isp_filter:
        query = query.filter(Proxy.isp.like(f"%{isp_filter}%"))
    
    import json
    try:
        adv_rules = json.loads(adv_search_json)
        for rule in adv_rules:
            col = rule.get('column', '')
            op = rule.get('operator', 'contains')
            val = rule.get('value', '')
            if not col or not val:
                continue
            column = getattr(Proxy, col, None)
            if column is None:
                continue
            if op == 'contains':
                query = query.filter(column.like(f"%{val}%"))
            elif op == 'equals':
                query = query.filter(column == val)
            elif op == 'starts':
                query = query.filter(column.like(f"{val}%"))
            elif op == 'gt':
                query = query.filter(column > val)
            elif op == 'lt':
                query = query.filter(column < val)
            elif op == 'gte':
                query = query.filter(column >= val)
            elif op == 'lte':
                query = query.filter(column <= val)
    except:
        pass
    
    proxies = query.all()
    
    if cols_param:
        cols = [c.strip() for c in cols_param.split(',') if c.strip()]
        col_map = {
            'protocol': 'protocol', 'port': 'port', 'cost': 'cost', 'speed': 'speed_ms',
            'alive': 'alive_hits', 'fails': 'fail_hits', 'country': 'countryCode',
            'region': 'regionName', 'city': 'city', 'isp': 'isp', 'asn': 'asn',
            'org': 'org', 'mobile': 'mobile', 'hosting': 'hosting',
            'lastalive': 'last_alive', 'lastcheck': 'last_checked'
        }
        selected_cols = ['ip'] + [col_map.get(c, c) for c in cols if c in col_map]
    else:
        selected_cols = None

    if fmt == "json":
        data = []
        for p in proxies:
            obj = p.to_dict()
            if selected_cols:
                obj = {k: v for k, v in obj.items() if k in selected_cols}
            username = str(p.username) if p.username is not None else ""
            password = str(p.password) if p.password is not None else ""
            if username and password:
                obj['proxy_url'] = f"{p.protocol}://{username}:{password}@{p.ip}:{p.port}"
            data.append(obj)
        return jsonify(data)

    lines = []
    first = True
    
    for p in proxies:
        row_dict = p.to_dict()
        
        if selected_cols:
            row_dict = {k: v for k, v in row_dict.items() if k in selected_cols}
        
        cols_list = list(row_dict.keys())
        
        if first and fmt == "csv":
            lines.append(','.join(cols_list))
            first = False
        
        vals = []
        for c in cols_list:
            val = row_dict.get(c, '')
            if val is None:
                val = ''
            else:
                val = str(val)
                if ',' in val or '"' in val or '\n' in val:
                    val = '"' + val.replace('"', '""') + '"'
            vals.append(val)
        
        lines.append(','.join(vals))
    
    return "\n".join(lines), 200, {"Content-Type": "text/csv" if fmt == "csv" else "text/plain"}
