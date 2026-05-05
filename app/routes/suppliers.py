from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from app.utils.permissions import permission_required

from app.services.supplier_service import (
    SupplierServiceError,
    add_article_to_supplier,
    create_supplier,
    get_supplier_or_404,
    get_supplier_article_links,
    list_suppliers,
    remove_article_from_supplier,
    search_active_articles,
    toggle_supplier_status,
    update_supplier,
)

suppliers_bp = Blueprint(
    "suppliers",
    __name__,
    url_prefix="/suppliers",
)


@suppliers_bp.route("/")
@login_required
@permission_required("proveedores")
def index():
    search = request.args.get("search")
    suppliers = list_suppliers(include_inactive=True, search=search)

    return render_template(
        "suppliers/index.html",
        suppliers=suppliers,
        search=search,
    )


@suppliers_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        try:
            create_supplier(
                code=request.form.get("code"),
                commercial_name=request.form.get("commercial_name"),
                legal_name=request.form.get("legal_name"),
                tax_id=request.form.get("tax_id"),
                contact_name=request.form.get("contact_name"),
                email=request.form.get("email"),
                phone=request.form.get("phone"),
                address=request.form.get("address"),
                payment_terms=request.form.get("payment_terms"),
                currency_code=request.form.get("currency_code"),
            )

            flash("Proveedor creado correctamente.", "success")
            return redirect(url_for("suppliers.index"))

        except SupplierServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "suppliers/form.html",
        supplier=None,
        form_title="Nuevo proveedor",
        submit_label="Crear proveedor",
    )


@suppliers_bp.route("/<int:supplier_id>/edit", methods=["GET", "POST"])
@login_required
def edit(supplier_id):
    supplier = get_supplier_or_404(supplier_id)

    if request.method == "POST":
        try:
            update_supplier(
                supplier_id=supplier.id,
                code=request.form.get("code"),
                commercial_name=request.form.get("commercial_name"),
                legal_name=request.form.get("legal_name"),
                tax_id=request.form.get("tax_id"),
                contact_name=request.form.get("contact_name"),
                email=request.form.get("email"),
                phone=request.form.get("phone"),
                address=request.form.get("address"),
                payment_terms=request.form.get("payment_terms"),
                currency_code=request.form.get("currency_code"),
                is_active=request.form.get("is_active") == "on",
            )

            flash("Proveedor actualizado correctamente.", "success")
            return redirect(url_for("suppliers.index"))

        except SupplierServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "suppliers/form.html",
        supplier=supplier,
        form_title=f"Editar proveedor {supplier.commercial_name}",
        submit_label="Guardar cambios",
    )


@suppliers_bp.route("/<int:supplier_id>/toggle-active", methods=["POST"])
@login_required
def toggle_active(supplier_id):
    toggle_supplier_status(supplier_id)
    flash("Estado del proveedor actualizado.", "success")
    return redirect(url_for("suppliers.index"))


@suppliers_bp.route("/<int:supplier_id>", methods=["GET"])
@login_required
def detail(supplier_id):
    supplier = get_supplier_or_404(supplier_id)

    search = request.args.get("search")
    articles = search_active_articles(search=search)
    article_links = get_supplier_article_links(supplier_id, include_inactive=True)

    return render_template(
        "suppliers/detail.html",
        supplier=supplier,
        articles=articles,
        article_links=article_links,
        search=search,
    )


@suppliers_bp.route("/<int:supplier_id>/add-article", methods=["POST"])
@login_required
def add_article(supplier_id):
    try:
        add_article_to_supplier(
            supplier_id=supplier_id,
            article_id=request.form.get("article_id"),
        )
        flash("Artículo agregado al proveedor.", "success")

    except SupplierServiceError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("suppliers.detail", supplier_id=supplier_id))


@suppliers_bp.route("/<int:supplier_id>/remove-article/<int:link_id>", methods=["POST"])
@login_required
def remove_article(supplier_id, link_id):
    try:
        remove_article_from_supplier(
            supplier_id=supplier_id,
            article_supplier_id=link_id,
        )
        flash("Artículo removido del proveedor.", "success")

    except SupplierServiceError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("suppliers.detail", supplier_id=supplier_id))