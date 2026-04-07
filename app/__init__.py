from flask import Flask, render_template, session
from flask_login import current_user

from .config import Config
from .extensions import db, jwt, login_manager, migrate
from .models.user import User
from .models.site import Site
from app.routes.bulk_routes import bulk_bp
from .routes.purchases_routes import purchases_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    login_manager.init_app(app)

    from . import models

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from .routes.auth_routes import auth_bp
    from .routes.dashboard_routes import dashboard_bp
    from .routes.work_order_routes import work_order_bp
    from .routes.work_order_requests import work_order_request_bp
    from .routes.deletion_routes import deletion_bp
    from .routes.waste_routes import waste_bp
    from .routes.report_routes import report_bp
    from .routes.purchases_routes import purchases_bp
    from .routes.mechanic_routes import mechanic_bp
    from .routes.mechanic_terminal_routes import terminal_bp
    from app.routes.articles_routes import articles_bp
    from app.routes.inventory_routes import inventory_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/")
    app.register_blueprint(articles_bp, url_prefix="/articles")
    app.register_blueprint(work_order_bp, url_prefix="/work-orders")
    app.register_blueprint(work_order_request_bp)
    app.register_blueprint(deletion_bp, url_prefix="/deletions")
    app.register_blueprint(waste_bp, url_prefix="/waste")
    app.register_blueprint(report_bp, url_prefix="/reports")
    app.register_blueprint(bulk_bp)
    app.register_blueprint(purchases_bp, url_prefix="/purchases")
    app.register_blueprint(inventory_bp, url_prefix="/inventory")
    app.register_blueprint(mechanic_bp)
    app.register_blueprint(terminal_bp)

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    @app.context_processor
    def inject_global_template_data():
        active_site = None
        sites = []

        if current_user.is_authenticated:
            # Obtener todos los predios activos
            sites = Site.query.filter_by(is_active=True).all()

            active_site_id = session.get("active_site_id")

            if active_site_id:
                active_site = Site.query.get(active_site_id)

            # Si no hay predio activo, asignar el primero disponible
            if not active_site and sites:
                active_site = sites[0]
                session["active_site_id"] = active_site.id

        return {
            "current_user": current_user,
            "active_site": active_site,
            "sites": sites,
        }

    return app