import os
import secrets
from datetime import datetime, timezone
from time import monotonic

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from dashboard.decorators import login_required
from dashboard.security import (
    api_error,
    clear_rate_limit,
    init_security,
    rate_limited,
    record_rate_limit_hit,
)
from database import db, ensure_db_schema


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_app():
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    configured_secret = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY")
    app.secret_key = configured_secret or secrets.token_hex(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower()
        in {"1", "true", "yes", "on"},
        MAX_CONTENT_LENGTH=max(64 * 1024, int(os.environ.get("MAX_REQUEST_BYTES", str(4 * 1024 * 1024)))),
    )
    if not configured_secret:
        app.logger.warning(
            "FLASK_SECRET_KEY is not configured; browser sessions will reset on restart. "
            "Set a random secret in .env before regular use."
        )
    if not os.environ.get("JWT_SECRET"):
        app.logger.warning(
            "JWT_SECRET is not configured; API tokens will reset on restart. "
            "Set an independent random secret in .env before regular use."
        )

    init_security(app)

    # A brand-new SQLite/MySQL database must be usable on first startup.
    ensure_db_schema()

    def get_db():
        """Get a database session scoped to the current Flask request."""
        if "db_session" not in g:
            g.db_session = db.get_session()
        return g.db_session

    @app.teardown_appcontext
    def close_db(_exc):
        db_session = g.pop("db_session", None)
        if db_session:
            db_session.close()

    from dashboard.routes import (
        import_export_bp,
        monitor_bp,
        proxies_bp,
        server_bp,
        settings_bp,
        stats_bp,
        users_bp,
    )

    app.register_blueprint(proxies_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(server_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(import_export_bp)
    app.register_blueprint(users_bp)

    import bcrypt

    from dashboard.config import USERS
    from dashboard.decorators import (
        cleanup_expired_tokens,
        create_token,
        delete_user_tokens,
    )
    from database import User

    token_cleanup_interval = max(
        60, int(os.environ.get("TOKEN_CLEANUP_INTERVAL_SECONDS", "900"))
    )
    app.extensions["token_cleanup_next_at"] = 0.0

    @app.before_request
    def periodically_cleanup_expired_tokens():
        """Avoid a DELETE/COMMIT on every incoming request."""
        now = monotonic()
        if now < app.extensions["token_cleanup_next_at"]:
            return None
        cleanup_expired_tokens()
        app.extensions["token_cleanup_next_at"] = now + token_cleanup_interval
        return None

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            os.path.join(app.static_folder, "img"),
            "favicon.ico",
            mimetype="image/vnd.microsoft.icon",
            max_age=86400,
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if rate_limited("browser-login", limit=10, window_seconds=300):
                flash("Too many failed sign-in attempts. Try again later.", "error")
                return render_template("login.html"), 429

            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            with db.session() as db_session:
                user = (
                    db_session.query(User)
                    .filter_by(username=username, is_active=True)
                    .first()
                )
                if user and bcrypt.checkpw(
                    password.encode("utf-8"), user.password_hash.encode("utf-8")
                ):
                    user.last_login = _utcnow_naive()
                    db_session.commit()
                    session.clear()
                    session["user"] = user.username
                    session["user_id"] = user.id
                    clear_rate_limit("browser-login")
                    return redirect(url_for("index"))

                if username in USERS and USERS[username] == password:
                    session.clear()
                    session["user"] = username
                    session["user_id"] = 0
                    clear_rate_limit("browser-login")
                    return redirect(url_for("index"))

            record_rate_limit_hit("browser-login")
            flash("Invalid credentials", "error")

        return render_template("login.html", auth_configured=bool(USERS))

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        user_id = session.get("user_id")
        if user_id and user_id > 0:
            delete_user_tokens(user_id)
        session.clear()
        return redirect(url_for("login"))

    @app.route("/api/login", methods=["POST"])
    def api_login():
        """Return a JWT for non-browser API clients."""
        if rate_limited("api-login", limit=10, window_seconds=300):
            return api_error("Too many failed sign-in attempts", 429, "rate_limited")

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return api_error("A JSON object is required", 400, "invalid_json")
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))

        with db.session() as db_session:
            user = (
                db_session.query(User)
                .filter_by(username=username, is_active=True)
                .first()
            )
            if user and bcrypt.checkpw(
                password.encode("utf-8"), user.password_hash.encode("utf-8")
            ):
                user.last_login = _utcnow_naive()
                db_session.commit()
                token = create_token(user.id)
                clear_rate_limit("api-login")
                return jsonify(
                    {"success": True, "token": token, "user": user.to_dict()}
                )

        record_rate_limit_hit("api-login")
        return api_error("Invalid credentials", 401, "invalid_credentials")

    @app.route("/")
    @app.route("/index")
    @login_required
    def index():
        allowed_tabs = {"cockpit", "proxies", "import", "monitor", "server", "stats", "operations", "users"}
        requested_tab = request.args.get("tab", "cockpit")
        tab = requested_tab if requested_tab in allowed_tabs else "cockpit"
        current_username = session.get("user")

        from dashboard.decorators import get_user_proxy_filters

        proxy_filters = {"statuses": [], "protocols": []}
        user_id = session.get("user_id")
        if user_id:
            with db.session() as db_session:
                db_user = db_session.query(User).filter_by(id=user_id).first()
                if db_user:
                    proxy_filters = get_user_proxy_filters(db_user)

        return render_template(
            "main.html",
            tab=tab,
            user=current_username,
            proxy_filters=proxy_filters,
        )

    return app
