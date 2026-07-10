import os
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
    session,
    url_for,
)

from dashboard.decorators import login_required
from database import db, ensure_db_schema


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_app():
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.secret_key = os.environ.get(
        "FLASK_SECRET_KEY",
        os.environ.get("SECRET_KEY", os.urandom(32).hex()),
    )
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower()
        in {"1", "true", "yes", "on"},
    )

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

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
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
                    session["user"] = user.username
                    session["user_id"] = user.id
                    create_token(user.id)
                    return redirect(url_for("index"))

                if username in USERS and USERS[username] == password:
                    session["user"] = username
                    session["user_id"] = 0
                    return redirect(url_for("index"))

                flash("Invalid credentials", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        user_id = session.get("user_id")
        if user_id and user_id > 0:
            delete_user_tokens(user_id)
        session.pop("user", None)
        session.pop("user_id", None)
        return redirect(url_for("login"))

    @app.route("/api/login", methods=["POST"])
    def api_login():
        """API login that returns a JWT token for database-backed users."""
        data = request.get_json(silent=True) or {}
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
                return jsonify(
                    {"success": True, "token": token, "user": user.to_dict()}
                )

            if username in USERS and USERS[username] == password:
                return jsonify(
                    {
                        "success": True,
                        "token": None,
                        "user": {"username": username, "role": "admin"},
                    }
                )

        return jsonify({"success": False, "error": "Invalid credentials"}), 401

    @app.route("/")
    @app.route("/index")
    @login_required
    def index():
        tab = request.args.get("tab", "cockpit")
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
