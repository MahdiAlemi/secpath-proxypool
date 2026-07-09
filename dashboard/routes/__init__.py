# Dashboard routes
from dashboard.routes.proxies import proxies_bp
from dashboard.routes.monitor import monitor_bp
from dashboard.routes.server import server_bp
from dashboard.routes.stats import stats_bp
from dashboard.routes.settings import settings_bp
from dashboard.routes.import_export import import_export_bp
from dashboard.routes.users import users_bp

__all__ = [
    "proxies_bp",
    "monitor_bp", 
    "server_bp",
    "stats_bp",
    "settings_bp",
    "import_export_bp",
    "users_bp"
]
