from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.models.site import Site
from app.models.user import User
from app.models.user_site_access import UserSiteAccess
from app.services.audit_service import log_action

auth_bp = Blueprint("auth", __name__)


def _set_initial_active_site(user: User) -> None:
    session.pop("active_site_id", None)

    if user.role and user.role.code == "SUPER_USUARIO":
        site = (
            Site.query
            .filter(Site.is_active.is_(True))
            .order_by(Site.id.asc())
            .first()
        )

        if site:
            session["active_site_id"] = site.id

        return

    site_access = (
        UserSiteAccess.query
        .join(Site, Site.id == UserSiteAccess.site_id)
        .filter(
            UserSiteAccess.user_id == user.id,
            Site.is_active.is_(True),
        )
        .order_by(Site.id.asc())
        .first()
    )

    if site_access:
        session["active_site_id"] = site_access.site_id


@auth_bp.route("/login", methods=["GET"])
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("home.index"))

    return render_template("auth/login.html")


@auth_bp.route("/login", methods=["POST"])
def login():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if not username:
        flash("El usuario es obligatorio.", "warning")
        return render_template("auth/login.html"), 400

    if not password:
        flash("La contraseña es obligatoria.", "warning")
        return render_template("auth/login.html"), 400

    user = User.query.filter_by(username=username).first()

    if not user:
        flash("Usuario o contraseña inválidos.", "danger")
        return render_template("auth/login.html"), 401

    if not user.is_active:
        flash("Este usuario se encuentra inactivo.", "danger")
        return render_template("auth/login.html"), 403

    if not user.check_password(password):
        flash("Usuario o contraseña inválidos.", "danger")
        return render_template("auth/login.html"), 401

    login_user(user, remember=False)
    session.permanent = False
    _set_initial_active_site(user)

    try:
        log_action(
            user_id=user.id,
            action="LOGIN",
            table_name="users",
            record_id=str(user.id),
            details={"username": user.username},
            commit=True,
        )
    except Exception:
        pass

    flash(f"Bienvenido, {user.full_name}.", "success")
    return redirect(url_for("home.index"))


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    user_id = current_user.id
    username = current_user.username

    try:
        log_action(
            user_id=user_id,
            action="LOGOUT",
            table_name="users",
            record_id=str(user_id),
            details={"username": username},
            commit=True,
        )
    except Exception:
        pass

    session.pop("active_site_id", None)

    logout_user()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("auth.login_page"))