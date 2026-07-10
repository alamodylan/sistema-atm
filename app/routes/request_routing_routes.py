from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
)
from flask_login import login_required, current_user

from app.extensions import db
from app.models.site import Site
from app.models.request_routing_rule import RequestRoutingRule
from sqlalchemy import text
from app.models.mechanic import Mechanic


request_routing_bp = Blueprint(
    "request_routing",
    __name__,
    url_prefix="/request-routing",
)


# =========================================================
# HELPERS
# =========================================================

def _require_superuser():
    """
    Valida acceso usando:
    1. Permiso configuracion_solicitudes por role_permissions.
    2. Código de rol ADMIN o SUPER_USUARIO.
    """

    if not current_user.is_authenticated:
        abort(403)

    role_id = getattr(current_user, "role_id", None)

    if not role_id:
        abort(403)

    sql = text("""
        SELECT 1
        FROM atm.roles r
        LEFT JOIN atm.role_permissions rp
            ON rp.role_id = r.id
        LEFT JOIN atm.permissions p
            ON p.id = rp.permission_id
        WHERE r.id = :role_id
        AND (
            r.code IN ('ADMIN', 'SUPER_USUARIO')
            OR p.code = 'configuracion_solicitudes'
        )
        LIMIT 1
    """)

    result = db.session.execute(sql, {"role_id": role_id}).first()

    if result:
        return

    abort(403)

def _get_sites():
    return (
        Site.query
        .filter(Site.is_active.is_(True))
        .order_by(Site.name.asc())
        .all()
    )


def _validate_form(origin_site_id, request_type, routing_mode, target_site_id):
    errors = []

    if not origin_site_id:
        errors.append("Debe seleccionar el predio origen.")

    if request_type not in RequestRoutingRule.REQUEST_TYPES:
        errors.append("Tipo de solicitud inválido.")

    if routing_mode not in RequestRoutingRule.ROUTING_MODES:
        errors.append("Modo de enrutamiento inválido.")

    if routing_mode == "OTHER_SITE_MANAGER_DASHBOARD" and not target_site_id:
        errors.append("Debe seleccionar el predio destino.")

    if routing_mode != "OTHER_SITE_MANAGER_DASHBOARD":
        target_site_id = None

    if request_type == "PURCHASE_REQUEST" and routing_mode == "DIRECT_TO_WAREHOUSE":
        errors.append("Compras no puede enviarse directo a bodega. Use directo a proveeduría.")

    if request_type != "PURCHASE_REQUEST" and routing_mode == "DIRECT_TO_PROCUREMENT":
        errors.append("Solo compras puede enviarse directo a proveeduría.")

    return errors, target_site_id


# =========================================================
# LISTADO
# =========================================================

@request_routing_bp.route("/", methods=["GET"])
@login_required
def index():
    _require_superuser()

    rules = (
        RequestRoutingRule.query
        .order_by(
            RequestRoutingRule.origin_site_id.asc(),
            RequestRoutingRule.request_type.asc(),
        )
        .all()
    )

    sites = _get_sites()

    terminal_modes = [
        {
            "value": Site.TERMINAL_MODE_BARCODE,
            "label": "Código de barras",
            "description": (
                "El mecánico accede escaneando su gafete y confirma "
                "la recepción escaneando nuevamente."
            ),
        },
        {
            "value": Site.TERMINAL_MODE_PROFILES_PIN,
            "label": "Perfiles de mecánicos con PIN",
            "description": (
                "El Terminal muestra los perfiles de los mecánicos y "
                "la recepción se confirma con un PIN de cuatro dígitos."
            ),
        },
    ]

    return render_template(
        "request_routing/index.html",
        rules=rules,
        sites=sites,
        request_types=RequestRoutingRule.REQUEST_TYPES,
        routing_modes=RequestRoutingRule.ROUTING_MODES,
        terminal_modes=terminal_modes,
    )

# =========================================================
# CONFIGURAR MODO DEL TERMINAL TALLER POR PREDIO
# =========================================================

@request_routing_bp.route("/terminal-mode/save", methods=["POST"])
@login_required
def save_terminal_mode():
    _require_superuser()

    site_id = request.form.get("site_id", type=int)
    terminal_mode = (
        request.form.get("mechanic_terminal_mode") or ""
    ).strip().upper()

    if not site_id:
        flash("Debe seleccionar un predio.", "danger")
        return redirect(url_for("request_routing.index"))

    if terminal_mode not in Site.TERMINAL_MODES:
        flash("El modo seleccionado para el Terminal Taller no es válido.", "danger")
        return redirect(url_for("request_routing.index"))

    site = (
        Site.query
        .filter(
            Site.id == site_id,
            Site.is_active.is_(True),
        )
        .first()
    )

    if not site:
        flash("El predio seleccionado no existe o está inactivo.", "danger")
        return redirect(url_for("request_routing.index"))

    try:
        site.mechanic_terminal_mode = terminal_mode
        db.session.commit()

        if terminal_mode == Site.TERMINAL_MODE_PROFILES_PIN:
            mechanics_without_pin = (
                db.session.query(Mechanic.id)
                .filter(
                    Mechanic.site_id == site.id,
                    Mechanic.is_active.is_(True),
                    Mechanic.pin_hash.is_(None),
                )
                .count()
            )

            if mechanics_without_pin > 0:
                flash(
                    (
                        f"Modo de perfiles con PIN activado para {site.name}. "
                        f"Hay {mechanics_without_pin} mecánico(s) activo(s) "
                        "sin PIN configurado."
                    ),
                    "warning",
                )
            else:
                flash(
                    f"Modo de perfiles con PIN activado para {site.name}.",
                    "success",
                )
        else:
            flash(
                f"Modo tradicional por código de barras activado para {site.name}.",
                "success",
            )

    except Exception as exc:
        db.session.rollback()
        print(f"[SAVE TERMINAL MODE ERROR] {exc}")
        flash(
            "No se pudo guardar el modo del Terminal Taller.",
            "danger",
        )

    return redirect(url_for("request_routing.index"))


# =========================================================
# CREAR / ACTUALIZAR REGLA
# =========================================================

@request_routing_bp.route("/save", methods=["POST"])
@login_required
def save():
    _require_superuser()

    rule_id = request.form.get("rule_id", type=int)

    origin_site_id = request.form.get("origin_site_id", type=int)
    request_type = (request.form.get("request_type") or "").strip()
    routing_mode = (request.form.get("routing_mode") or "").strip()
    target_site_id = request.form.get("target_site_id", type=int)
    is_active = request.form.get("is_active") == "on"

    errors, target_site_id = _validate_form(
        origin_site_id=origin_site_id,
        request_type=request_type,
        routing_mode=routing_mode,
        target_site_id=target_site_id,
    )

    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("request_routing.index"))

    try:
        if rule_id:
            rule = RequestRoutingRule.query.get_or_404(rule_id)

            existing = (
                RequestRoutingRule.query
                .filter(
                    RequestRoutingRule.origin_site_id == origin_site_id,
                    RequestRoutingRule.request_type == request_type,
                    RequestRoutingRule.id != rule.id,
                )
                .first()
            )

            if existing:
                flash(
                    "Ya existe una configuración para ese predio y tipo de solicitud.",
                    "warning",
                )
                return redirect(url_for("request_routing.index"))

        else:
            existing = (
                RequestRoutingRule.query
                .filter(
                    RequestRoutingRule.origin_site_id == origin_site_id,
                    RequestRoutingRule.request_type == request_type,
                )
                .first()
            )

            if existing:
                flash(
                    "Ya existe una configuración para ese predio y tipo de solicitud.",
                    "warning",
                )
                return redirect(url_for("request_routing.index"))

            rule = RequestRoutingRule(
                created_by_user_id=current_user.id,
            )
            db.session.add(rule)

        rule.origin_site_id = origin_site_id
        rule.request_type = request_type
        rule.routing_mode = routing_mode
        rule.target_site_id = target_site_id
        rule.is_active = is_active

        db.session.commit()

        flash("Configuración guardada correctamente.", "success")

    except Exception as exc:
        db.session.rollback()
        flash(f"No se pudo guardar la configuración: {exc}", "danger")

    return redirect(url_for("request_routing.index"))


# =========================================================
# ACTIVAR / DESACTIVAR
# =========================================================

@request_routing_bp.route("/<int:rule_id>/toggle", methods=["POST"])
@login_required
def toggle(rule_id):
    _require_superuser()

    rule = RequestRoutingRule.query.get_or_404(rule_id)

    try:
        rule.is_active = not rule.is_active
        db.session.commit()

        if rule.is_active:
            flash("Configuración activada correctamente.", "success")
        else:
            flash("Configuración desactivada correctamente.", "warning")

    except Exception as exc:
        db.session.rollback()
        flash(f"No se pudo cambiar el estado: {exc}", "danger")

    return redirect(url_for("request_routing.index"))


# =========================================================
# ELIMINAR
# =========================================================

@request_routing_bp.route("/<int:rule_id>/delete", methods=["POST"])
@login_required
def delete(rule_id):
    _require_superuser()

    rule = RequestRoutingRule.query.get_or_404(rule_id)

    try:
        db.session.delete(rule)
        db.session.commit()
        flash("Configuración eliminada correctamente.", "success")

    except Exception as exc:
        db.session.rollback()
        flash(f"No se pudo eliminar la configuración: {exc}", "danger")

    return redirect(url_for("request_routing.index"))