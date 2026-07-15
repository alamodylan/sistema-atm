from flask import (
    Flask,
    make_response,
    render_template,
    request,
    send_from_directory,
    session,
)
from flask_login import current_user
from sqlalchemy.orm import lazyload, selectinload

from .config import Config
from .extensions import db, jwt, login_manager, migrate

from .models.role import Role
from .models.role_permission import RolePermission
from .models.site import Site
from .models.user import User

from app.models.user_site_access import UserSiteAccess
from app.routes.bulk_routes import bulk_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # =========================================================
    # EXTENSIONES
    # =========================================================
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    login_manager.init_app(app)

    # Importa todos los modelos para que SQLAlchemy registre
    # correctamente relaciones y metadatos.
    from . import models

    # =========================================================
    # CARGA DEL USUARIO AUTENTICADO
    # =========================================================
    @login_manager.user_loader
    def load_user(user_id):
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return None

        return (
            User.query
            .options(
                # Precarga el rol.
                selectinload(User.role)
                # Precarga los permisos asociados al rol.
                .selectinload(Role.role_permissions)
                # Precarga cada permiso.
                .selectinload(RolePermission.permission),

                # Estas relaciones no deben cargarse automáticamente
                # en todas las peticiones. Se cargarán únicamente cuando
                # alguna función acceda realmente a ellas.
                lazyload(User.site_accesses),
                lazyload(User.warehouse_accesses),
            )
            .filter(User.id == user_id)
            .first()
        )

    # =========================================================
    # IMPORTACIÓN DE BLUEPRINTS
    # =========================================================
    from .routes.auth_routes import auth_bp
    from .routes.dashboard_routes import dashboard_bp
    from .routes.deletion_routes import deletion_bp
    from .routes.mechanic_routes import mechanic_bp
    from .routes.mechanic_terminal_routes import terminal_bp
    from .routes.purchases_routes import purchases_bp
    from .routes.repair_type_routes import repair_type_bp
    from .routes.report_routes import report_bp
    from .routes.waste_routes import waste_bp
    from .routes.work_order_requests import work_order_request_bp
    from .routes.work_order_routes import work_order_bp
    from.routes.article_code_routes import article_code_bp

    from app.routes.articles_routes import articles_bp
    from app.routes.audit_routes import audit_bp
    from app.routes.equipment import equipment_bp
    from app.routes.home import home_bp
    from app.routes.inventory_adjustments import inventory_adjustments_bp
    from app.routes.inventory_routes import inventory_bp
    from app.routes.kardex import kardex_bp
    from app.routes.notifications import notification_bp
    from app.routes.physical_inventory_routes import physical_inventory_bp
    from app.routes.request_routing_routes import request_routing_bp
    from app.routes.stats_routes import stats_bp
    from app.routes.stats_routes_equipos import equipment_stats_bp
    from app.routes.suppliers import suppliers_bp
    from app.routes.tool_loans_routes import tool_loans_bp
    from app.routes.transfer_routes import transfer_bp
    from app.routes.users import users_bp

    from app.utils.datetime_helpers import format_costa_rica_datetime

    # =========================================================
    # REGISTRO DE BLUEPRINTS
    # =========================================================
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/")

    app.register_blueprint(
        articles_bp,
        url_prefix="/articles",
    )

    app.register_blueprint(
        work_order_bp,
        url_prefix="/work-orders",
    )

    app.register_blueprint(work_order_request_bp)

    app.register_blueprint(
        deletion_bp,
        url_prefix="/deletions",
    )

    app.register_blueprint(
        waste_bp,
        url_prefix="/waste",
    )

    app.register_blueprint(
        report_bp,
        url_prefix="/reports",
    )

    app.register_blueprint(bulk_bp)

    app.register_blueprint(
        purchases_bp,
        url_prefix="/purchases",
    )

    app.register_blueprint(
        inventory_bp,
        url_prefix="/inventory",
    )

    app.register_blueprint(mechanic_bp)
    app.register_blueprint(terminal_bp)
    app.register_blueprint(transfer_bp)
    app.register_blueprint(repair_type_bp)
    app.register_blueprint(physical_inventory_bp)
    app.register_blueprint(inventory_adjustments_bp)
    app.register_blueprint(kardex_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(equipment_stats_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(tool_loans_bp)
    app.register_blueprint(request_routing_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(article_code_bp)

    # =========================================================
    # FILTROS JINJA
    # =========================================================
    app.jinja_env.filters[
        "cr_datetime"
    ] = format_costa_rica_datetime

    # =========================================================
    # SERVICE WORKER
    # =========================================================
    @app.route("/service-worker.js")
    def service_worker():
        response = make_response(
            send_from_directory(
                "static",
                "service-worker.js",
            )
        )

        response.headers[
            "Content-Type"
        ] = "application/javascript"

        response.headers[
            "Service-Worker-Allowed"
        ] = "/"

        return response

    # =========================================================
    # MANEJADORES DE ERRORES
    # =========================================================
    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template(
            "errors/403.html"
        ), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template(
            "errors/404.html"
        ), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()

        return render_template(
            "errors/500.html"
        ), 500

    # =========================================================
    # CONTEXTO GLOBAL DE PLANTILLAS
    # =========================================================
    @app.context_processor
    def inject_global_template_data():
        is_ajax = (
            request.headers.get("X-Requested-With")
            == "XMLHttpRequest"
        )

        if is_ajax:
            return {
                "current_user": current_user,
                "active_site": None,
                "sites": [],
            }

        active_site = None
        sites = []

        if not current_user.is_authenticated:
            return {
                "current_user": current_user,
                "active_site": None,
                "sites": [],
            }

        role = current_user.role

        # =====================================================
        # PREDIOS DISPONIBLES PARA SUPER USUARIO
        # =====================================================
        if role and role.code == "SUPER_USUARIO":
            sites = (
                Site.query
                .filter(
                    Site.is_active.is_(True)
                )
                .order_by(
                    Site.id.asc()
                )
                .all()
            )

        # =====================================================
        # PREDIOS DISPONIBLES PARA USUARIO NORMAL
        # =====================================================
        else:
            sites = (
                Site.query
                .join(
                    UserSiteAccess,
                    UserSiteAccess.site_id == Site.id,
                )
                .filter(
                    UserSiteAccess.user_id
                    == current_user.id,
                    Site.is_active.is_(True),
                )
                .order_by(
                    Site.id.asc()
                )
                .all()
            )

        active_site_id = session.get(
            "active_site_id"
        )

        if active_site_id is not None:
            try:
                active_site_id = int(
                    active_site_id
                )
            except (TypeError, ValueError):
                active_site_id = None

        # =====================================================
        # OBTENER EL PREDIO ACTIVO DESDE LA LISTA YA CONSULTADA
        # =====================================================
        if active_site_id is not None:
            active_site = next(
                (
                    site
                    for site in sites
                    if int(site.id)
                    == active_site_id
                ),
                None,
            )

            if active_site is None:
                session.pop(
                    "active_site_id",
                    None,
                )

        # =====================================================
        # SELECCIONAR EL PRIMER PREDIO CUANDO NO HAY ACTIVO
        # =====================================================
        if active_site is None and sites:
            active_site = sites[0]

            session[
                "active_site_id"
            ] = int(active_site.id)

        return {
            "current_user": current_user,
            "active_site": active_site,
            "sites": sites,
        }

    return app