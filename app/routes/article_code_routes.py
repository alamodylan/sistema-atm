from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.models.item_category import ItemCategory
from app.services.article_code_service import (
    ArticleCodeServiceError,
    create_manual_article_code,
    get_active_subcategories_by_category,
    get_article_code_form_catalogs,
    list_manual_article_codes,
)


article_codes_bp = Blueprint(
    "article_codes",
    __name__,
    url_prefix="/article-codes",
)


# =========================================================
# SEGURIDAD DEL MÓDULO
# =========================================================
def _require_super_user() -> None:
    """
    Impide el acceso al módulo a cualquier usuario que no tenga
    el rol SUPER_USUARIO.

    La validación se hace en backend, no solamente en el sidebar.
    """
    role = getattr(current_user, "role", None)

    if (
        not current_user.is_authenticated
        or not current_user.is_active
        or not role
        or not role.is_active
        or role.code != "SUPER_USUARIO"
    ):
        abort(403)


# =========================================================
# LISTADO DE CÓDIGOS CREADOS MANUALMENTE
# =========================================================
@article_codes_bp.route("/", methods=["GET"])
@login_required
def index():
    _require_super_user()

    page = request.args.get(
        "page",
        1,
        type=int,
    )

    search = (
        request.args.get("q")
        or ""
    ).strip()

    category_id = request.args.get(
        "category_id",
        type=int,
    )

    active_status = (
        request.args.get("active_status")
        or ""
    ).strip().upper()

    try:
        pagination = list_manual_article_codes(
            page=page,
            per_page=20,
            search=search,
            category_id=category_id,
            active_status=active_status,
        )

        # Solo se consultan las columnas necesarias para el filtro.
        categories = (
            db.session.query(
                ItemCategory.id,
                ItemCategory.code,
                ItemCategory.name,
            )
            .order_by(
                ItemCategory.name.asc(),
                ItemCategory.code.asc(),
            )
            .all()
        )

        return render_template(
            "article_codes/index.html",
            title="Creación de códigos",
            subtitle=(
                "Consulte los artículos creados manualmente "
                "y registre nuevos códigos."
            ),
            articles=pagination.items,
            pagination=pagination,
            categories=categories,
            search=search,
            selected_category_id=category_id,
            selected_active_status=active_status,
        )

    except Exception as exc:
        print(
            f"[ARTICLE CODES INDEX ERROR] "
            f"error={exc}"
        )

        flash(
            "Error al cargar los códigos creados manualmente.",
            "danger",
        )

        return render_template(
            "article_codes/index.html",
            title="Creación de códigos",
            subtitle=(
                "Consulte los artículos creados manualmente "
                "y registre nuevos códigos."
            ),
            articles=[],
            pagination=None,
            categories=[],
            search=search,
            selected_category_id=category_id,
            selected_active_status=active_status,
        )


# =========================================================
# FORMULARIO DE NUEVO CÓDIGO
# =========================================================
@article_codes_bp.route("/new", methods=["GET"])
@login_required
def new():
    _require_super_user()

    try:
        catalogs = get_article_code_form_catalogs()

        return render_template(
            "article_codes/form.html",
            title="Nuevo código",
            subtitle=(
                "Cree un artículo sin registrar existencias "
                "ni movimientos de inventario."
            ),
            units=catalogs["units"],
            categories=catalogs["categories"],
            form_data={},
        )

    except Exception as exc:
        print(
            f"[ARTICLE CODE FORM ERROR] "
            f"error={exc}"
        )

        flash(
            "Error al cargar el formulario de creación.",
            "danger",
        )

        return redirect(
            url_for("article_codes.index")
        )


# =========================================================
# CREAR CÓDIGO MANUAL
# =========================================================
@article_codes_bp.route("/new", methods=["POST"])
@login_required
def create():
    _require_super_user()

    form_data = request.form.to_dict(
        flat=True
    )

    try:
        category_mode = (
            request.form.get("category_mode")
            or "EXISTING"
        ).strip().upper()

        selected_category_id = request.form.get(
            "category_id",
            type=int,
        )

        selected_subcategory_id = request.form.get(
            "subcategory_id",
            type=int,
        )

        unit_id = request.form.get(
            "unit_id",
            type=int,
        )

        is_tool = (
            request.form.get("is_tool")
            == "on"
        )

        # El artículo se crea activo por defecto.
        # Si el checkbox existe y está desmarcado, llega ausente.
        is_active = (
            request.form.get("is_active")
            == "on"
        )

        article = create_manual_article_code(
            code=request.form.get("code"),
            name=request.form.get("name"),
            unit_id=unit_id,
            category_mode=category_mode,
            selected_category_id=selected_category_id,
            selected_subcategory_id=selected_subcategory_id,
            new_category_code=request.form.get(
                "new_category_code"
            ),
            new_category_name=request.form.get(
                "new_category_name"
            ),
            new_category_description=request.form.get(
                "new_category_description"
            ),
            description=request.form.get(
                "description"
            ),
            family_code=request.form.get(
                "family_code"
            ),
            barcode=request.form.get(
                "barcode"
            ),
            sap_code=request.form.get(
                "sap_code"
            ),
            is_tool=is_tool,
            is_active=is_active,
            created_by_user_id=current_user.id,
            commit=True,
        )

        flash(
            f"El código {article.code} fue creado correctamente.",
            "success",
        )

        submit_action = (
            request.form.get("submit_action")
            or "save"
        ).strip().lower()

        if submit_action == "save_and_new":
            return redirect(
                url_for("article_codes.new")
            )

        return redirect(
            url_for("article_codes.index")
        )

    except ArticleCodeServiceError as exc:
        flash(
            str(exc),
            "danger",
        )

    except Exception as exc:
        db.session.rollback()

        print(
            f"[CREATE ARTICLE CODE ERROR] "
            f"user_id={current_user.id} "
            f"error={exc}"
        )

        flash(
            "Error interno al crear el código.",
            "danger",
        )

    # Si ocurre una validación, se recargan solamente los catálogos
    # pequeños y se conservan los valores ingresados.
    try:
        catalogs = get_article_code_form_catalogs()

    except Exception as catalog_exc:
        print(
            f"[ARTICLE CODE CATALOG ERROR] "
            f"error={catalog_exc}"
        )

        flash(
            "No se pudieron recargar los catálogos del formulario.",
            "danger",
        )

        return redirect(
            url_for("article_codes.index")
        )

    return render_template(
        "article_codes/form.html",
        title="Nuevo código",
        subtitle=(
            "Cree un artículo sin registrar existencias "
            "ni movimientos de inventario."
        ),
        units=catalogs["units"],
        categories=catalogs["categories"],
        form_data=form_data,
    )


# =========================================================
# SUBCATEGORÍAS ACTIVAS POR CATEGORÍA
# =========================================================
@article_codes_bp.route(
    "/categories/<int:category_id>/subcategories",
    methods=["GET"],
)
@login_required
def subcategories(category_id: int):
    _require_super_user()

    try:
        rows = get_active_subcategories_by_category(
            category_id=category_id
        )

        return jsonify(
            {
                "ok": True,
                "items": [
                    {
                        "id": row.id,
                        "code": row.code or "",
                        "name": row.name,
                        "label": (
                            f"{row.code} - {row.name}"
                            if row.code
                            else row.name
                        ),
                    }
                    for row in rows
                ],
            }
        )

    except Exception as exc:
        print(
            f"[ARTICLE SUBCATEGORIES ERROR] "
            f"category_id={category_id} "
            f"error={exc}"
        )

        return jsonify(
            {
                "ok": False,
                "message": (
                    "No se pudieron cargar las subcategorías."
                ),
                "items": [],
            }
        ), 500