import os
from flask import Flask, g, render_template, redirect, url_for, session, flash, request

from database import db
from dashboard.decorators import login_required


def create_app():
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.environ.get("SECRET_KEY", os.urandom(32).hex()))
    
    from dashboard.config import DB_PATH
    
    def get_db():
        """Get database session from Flask g object"""
        if "db_session" not in g:
            g.db_session = db.get_session()
        return g.db_session

    @app.teardown_appcontext
    def close_db(exc):
        """Close database session after request"""
        db_session = g.pop("db_session", None)
        if db_session:
            db_session.close()

    from dashboard.routes import proxies_bp, monitor_bp, server_bp, stats_bp, settings_bp, import_export_bp, users_bp
    
    app.register_blueprint(proxies_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(server_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(import_export_bp)
    app.register_blueprint(users_bp)
    
    from dashboard.config import USERS
    from dashboard.decorators import create_token, delete_token, delete_user_tokens, cleanup_expired_tokens
    from database import User
    import bcrypt
    
    @app.before_request
    def before_request():
        cleanup_expired_tokens()
    
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            
            with db.session() as db_session:
                user = db_session.query(User).filter_by(username=username, is_active=True).first()
                if user:
                    if bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
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
        user_id = session.get('user_id')
        if user_id and user_id > 0:
            delete_user_tokens(user_id)
        session.pop("user", None)
        session.pop("user_id", None)
        return redirect(url_for("login"))

    @app.route("/api/login", methods=["POST"])
    def api_login():
        """API login that returns JWT token"""
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "")
        
        with db.session() as db_session:
            user = db_session.query(User).filter_by(username=username, is_active=True).first()
            if user:
                if bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
                    user_data = user.to_dict()
                    token = create_token(user.id)
                    return jsonify({
                        "success": True,
                        "token": token,
                        "user": user_data
                    })
            
            if username in USERS and USERS[username] == password:
                return jsonify({
                    "success": True,
                    "token": None,
                    "user": {"username": username, "role": "admin"}
                })
        
        return jsonify({"success": False, "error": "Invalid credentials"}), 401

    @app.route("/")
    @app.route("/index")
    @login_required
    def index():
        tab = request.args.get("tab", "proxies")
        user = session.get("user")
        
        # Get user's proxy filters for server-side rendering
        from dashboard.decorators import get_user_proxy_filters
        from database import User, db
        
        proxy_filters = {"statuses": [], "protocols": []}
        user_id = session.get("user_id")
        if user_id:
            with db.session() as db_session:
                db_user = db_session.query(User).filter_by(id=user_id).first()
                if db_user:
                    proxy_filters = get_user_proxy_filters(db_user)
        
        return render_template("main.html", tab=tab, user=user, proxy_filters=proxy_filters)
    
    return app


from flask import jsonify
