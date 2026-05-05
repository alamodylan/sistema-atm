from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from app.utils.permissions import permission_required

from app.services.user_admin_service import (
    UserAdminServiceError,
    create_role,
    create_user,
    get_role_or_404,
    get_role_permission_ids,
    get_user_or_404,
    get_user_site_ids,
    get_user_warehouse_ids,
    list_permissions,
    list_roles,
    list_roles_with_permissions,
    list_sites,
    list_users,
    list_warehouses_grouped_by_site,
    toggle_user_status,
    update_role,
    update_user,
)

users_bp = Blueprint(
    "users",
    __name__,
    url_prefix="/users",
)


@users_bp.route("/")
@login_required
@permission_required("usuarios")
def index():
    users = list_users(include_inactive=True)

    return render_template(
        "users/index.html",
        users=users,
    )


@users_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    roles = list_roles(include_inactive=False)
    sites = list_sites(include_inactive=False)
    warehouses_by_site = list_warehouses_grouped_by_site(include_inactive=False)

    if request.method == "POST":
        try:
            create_user(
                username=request.form.get("username"),
                full_name=request.form.get("full_name"),
                email=request.form.get("email"),
                password=request.form.get("password"),
                role_id=request.form.get("role_id"),
                site_ids=request.form.getlist("site_ids"),
                warehouse_ids=request.form.getlist("warehouse_ids"),
                is_shared_account=request.form.get("is_shared_account") == "on",
                barcode_value=request.form.get("barcode_value"),
                created_by_user_id=current_user.id,
            )

            flash("Usuario creado correctamente.", "success")
            return redirect(url_for("users.index"))

        except UserAdminServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "users/form.html",
        user=None,
        roles=roles,
        sites=sites,
        warehouses_by_site=warehouses_by_site,
        selected_site_ids=[],
        selected_warehouse_ids=[],
        form_title="Nuevo usuario",
        submit_label="Crear usuario",
    )


@users_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit(user_id):
    user = get_user_or_404(user_id)

    roles = list_roles(include_inactive=False)
    sites = list_sites(include_inactive=False)
    warehouses_by_site = list_warehouses_grouped_by_site(include_inactive=False)

    selected_site_ids = get_user_site_ids(user)
    selected_warehouse_ids = get_user_warehouse_ids(user)

    if request.method == "POST":
        try:
            update_user(
                user_id=user.id,
                username=request.form.get("username"),
                full_name=request.form.get("full_name"),
                email=request.form.get("email"),
                password=request.form.get("password"),
                role_id=request.form.get("role_id"),
                site_ids=request.form.getlist("site_ids"),
                warehouse_ids=request.form.getlist("warehouse_ids"),
                is_active=request.form.get("is_active") == "on",
                is_shared_account=request.form.get("is_shared_account") == "on",
                barcode_value=request.form.get("barcode_value"),
            )

            flash("Usuario actualizado correctamente.", "success")
            return redirect(url_for("users.index"))

        except UserAdminServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "users/form.html",
        user=user,
        roles=roles,
        sites=sites,
        warehouses_by_site=warehouses_by_site,
        selected_site_ids=selected_site_ids,
        selected_warehouse_ids=selected_warehouse_ids,
        form_title=f"Editar usuario {user.username}",
        submit_label="Guardar cambios",
    )


@users_bp.route("/<int:user_id>/toggle-active", methods=["POST"])
@login_required
def toggle_active(user_id):
    toggle_user_status(user_id)
    flash("Estado del usuario actualizado.", "success")
    return redirect(url_for("users.index"))


@users_bp.route("/roles")
@login_required
def roles_index():
    roles = list_roles_with_permissions()

    return render_template(
        "users/roles_index.html",
        roles=roles,
    )


@users_bp.route("/roles/create", methods=["GET", "POST"])
@login_required
def roles_create():
    permissions = list_permissions()

    if request.method == "POST":
        try:
            create_role(
                code=request.form.get("code"),
                name=request.form.get("name"),
                description=request.form.get("description"),
                permission_ids=request.form.getlist("permission_ids"),
            )

            flash("Rol creado correctamente.", "success")
            return redirect(url_for("users.roles_index"))

        except UserAdminServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "users/role_form.html",
        role=None,
        permissions=permissions,
        selected_permission_ids=[],
        form_title="Nuevo rol / perfil",
        submit_label="Crear rol",
    )


@users_bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
@login_required
def roles_edit(role_id):
    role = get_role_or_404(role_id)
    permissions = list_permissions()
    selected_permission_ids = get_role_permission_ids(role)

    if request.method == "POST":
        try:
            update_role(
                role_id=role.id,
                code=request.form.get("code"),
                name=request.form.get("name"),
                description=request.form.get("description"),
                is_active=request.form.get("is_active") == "on",
                permission_ids=request.form.getlist("permission_ids"),
            )

            flash("Rol actualizado correctamente.", "success")
            return redirect(url_for("users.roles_index"))

        except UserAdminServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "users/role_form.html",
        role=role,
        permissions=permissions,
        selected_permission_ids=selected_permission_ids,
        form_title=f"Editar rol {role.name}",
        submit_label="Guardar cambios",
    )