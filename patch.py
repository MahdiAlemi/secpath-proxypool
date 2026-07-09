import sys

def patch_file(path, replacements):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for old, new in replacements:
        content = content.replace(old, new)
            
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

# 1. proxy_server/config.py
patch_file('/data/build/proxy_server/config.py', [
    ('parser.add_argument("--rotate",', 'parser.add_argument("--w_latency", type=float, default=0.4, help="Weight for latency cost")\n    parser.add_argument("--w_fail", type=float, default=0.4, help="Weight for failure cost")\n    parser.add_argument("--rotate",')
])

# 2. proxy_server/server/proxy_store.py
patch_file('/data/build/proxy_server/server/proxy_store.py', [
    ('            if cf < min_c or cf > max_c:\n                continue',
     '            if has_cost_filter:\n                if cf < min_c or cf > max_c:\n                    continue\n            elif cf < min_c:\n                continue')
])

# 3. proxy_monitor/utils/geo.py
patch_file('/data/build/proxy_monitor/utils/geo.py', [
    ('f"{{http://ip-api.com/json/{ip}}}?fields=', 'f"http://ip-api.com/json/{ip}?fields=')
])

# 4. proxy_monitor config & runner
patch_file('/data/build/proxy_monitor/monitor/runner.py', [
    ('from proxy_monitor.config import THREADS, PROBES_PER_PROXY, SHUFFLE_BIAS, SPEED_THRESHOLD_MS',
     'from proxy_monitor import config as pm_config\nSHUFFLE_BIAS = pm_config.SHUFFLE_BIAS\nSPEED_THRESHOLD_MS = pm_config.SPEED_THRESHOLD_MS'),
    ('range(THREADS)', 'range(pm_config.THREADS)'),
    ('PROBES_PER_PROXY', 'pm_config.PROBES_PER_PROXY')
])

patch_file('/data/build/proxy_monitor/workers/worker.py', [
    ('from proxy_monitor.config import PROBES_PER_PROXY, CHECK_URLS, TIMEOUT, THREADS',
     'from proxy_monitor import config as pm_config'),
    ('random.choice(CHECK_URLS)', 'random.choice(pm_config.CHECK_URLS)'),
    ('TIMEOUT', 'pm_config.TIMEOUT')
])

patch_file('/data/build/proxy_monitor/workers/tester.py', [
    ('from proxy_monitor.config import PROBES_PER_PROXY, CHECK_URLS, TIMEOUT, PROBE_JITTER',
     'from proxy_monitor import config as pm_config'),
    ('PROBES_PER_PROXY', 'pm_config.PROBES_PER_PROXY'),
    ('CHECK_URLS', 'pm_config.CHECK_URLS'),
    ('TIMEOUT', 'pm_config.TIMEOUT'),
    ('PROBE_JITTER', 'pm_config.PROBE_JITTER')
])

patch_file('/data/build/proxy_monitor/app.py', [
    ('    global ARGS\n    ARGS = parse_args()',
     '    global ARGS\n    ARGS = parse_args()\n    import proxy_monitor.config as pm_config\n    pm_config.THREADS = ARGS.threads\n    pm_config.TIMEOUT = ARGS.timeout\n    pm_config.PROBES_PER_PROXY = ARGS.probes\n    if ARGS.check_urls:\n        pm_config.CHECK_URLS = [u.strip() for u in ARGS.check_urls.split(",") if u.strip()]')
])

# 5. Dashboard config and decorators
patch_file('/data/build/dashboard/__init__.py', [
    ('app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32).hex())',
     'app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.environ.get("SECRET_KEY", os.urandom(32).hex()))')
])

patch_file('/data/build/dashboard/decorators.py', [
    ("    user_id = g.get('user_id') or session.get('user_id')\n    if not user_id:\n        return False",
     "    user_id = g.get('user_id')\n    if user_id is None:\n        user_id = session.get('user_id')\n    if user_id is None:\n        return False\n    if user_id == 0:\n        return True"),
    ("            user_id = g.get('user_id') or session.get('user_id')\n            if not user_id:\n                if request.is_json:\n                    return jsonify({'error': 'Authentication required'}), 401\n                return redirect(url_for(\"login\"))",
     "            user_id = g.get('user_id')\n            if user_id is None:\n                user_id = session.get('user_id')\n            if user_id is None:\n                if request.is_json:\n                    return jsonify({'error': 'Authentication required'}), 401\n                return redirect(url_for(\"login\"))\n            if user_id == 0:\n                return f(*args, **kwargs)"),
    ("    user_id = g.get('user_id') or session.get('user_id')\n    if not user_id:\n        return None",
     "    user_id = g.get('user_id')\n    if user_id is None:\n        user_id = session.get('user_id')\n    if user_id is None:\n        return None\n    if user_id == 0:\n        return {\n            'id': 0,\n            'username': session.get('user', 'admin'),\n            'role': 'admin',\n            'custom_permissions': {},\n            'is_active': True\n        }")
])

# 6. config.py SQLite
patch_file('/data/build/config.py', [
    ("    DB_NAME = os.getenv('DB_NAME', 'proxypool')",
     "    DB_NAME = os.getenv('DB_NAME', 'proxypool')\n    DB_TYPE = os.getenv('DB_TYPE', 'mysql')"),
    ('        return f"mysql+pymysql://{cls.DB_USER}:{cls.DB_PASS}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"',
     '        if getattr(cls, "DB_TYPE", "mysql").lower() == "sqlite":\n            return cls.get_sqlite_url()\n        return f"mysql+pymysql://{cls.DB_USER}:{cls.DB_PASS}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"')
])

print("Python patch script applied.")
