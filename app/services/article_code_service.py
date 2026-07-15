from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.article import Article
from app.models.item_category import ItemCategory
from app.models.item_subcategory import ItemSubcategory
from app.models.unit import Unit
from app.services.audit_service import log_action


class ArticleCodeServiceError(Exception):
    pass


# =========================================================
# CATÁLOGOS LIGEROS PARA EL FORMULARIO
# =========================================================
def get_article_code_form_catalogs():
    """
    Retorna únicamente los datos necesarios para construir
    los selectores del formulario.

    No carga relaciones ni objetos completos innecesarios.
    """

    units = (
        db.session.query(
            Unit.id,
            Unit.code,
            Unit.name,
        )
        .order_by(
            Unit.name.asc(),
            Unit.code.asc(),
        )
        .all()
    )

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

    return {
        "units": units,
        "categories": categories,
    }


# =========================================================
# SUBCATEGORÍAS POR CATEGORÍA
# =========================================================
def get_active_subcategories_by_category(
    category_id: int,
):
    """
    Retorna únicamente las subcategorías activas de una categoría.

    Esta función está pensada para el endpoint AJAX del formulario.
    """

    if not category_id:
        return []

    return (
        db.session.query(
            ItemSubcategory.id,
            ItemSubcategory.code,
            ItemSubcategory.name,
        )
        .filter(
            ItemSubcategory.category_id == int(category_id),
            ItemSubcategory.is_active.is_(True),
        )
        .order_by(
            ItemSubcategory.name.asc(),
            ItemSubcategory.id.asc(),
        )
        .all()
    )


# =========================================================
# CONSULTA PAGINADA DE CÓDIGOS MANUALES
# =========================================================
def list_manual_article_codes(
    *,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    category_id: int | None = None,
    active_status: str | None = None,
):
    """
    Lista exclusivamente artículos creados desde el módulo manual.

    Usa paginación y precarga relaciones escalares para evitar N+1.
    """

    safe_page = max(int(page or 1), 1)
    safe_per_page = max(
        1,
        min(int(per_page or 20), 100),
    )

    query = (
        Article.query
        .options(
            joinedload(Article.unit),
            joinedload(Article.category),
            joinedload(Article.subcategory),
            joinedload(Article.created_by_user),
        )
        .filter(
            Article.creation_source == "MANUAL"
        )
    )

    normalized_search = (
        search or ""
    ).strip()

    if normalized_search:
        like_value = f"%{normalized_search}%"

        query = query.filter(
            db.or_(
                Article.code.ilike(like_value),
                Article.name.ilike(like_value),
                Article.barcode.ilike(like_value),
                Article.sap_code.ilike(like_value),
            )
        )

    if category_id:
        query = query.filter(
            Article.category_id == int(category_id)
        )

    normalized_active_status = (
        active_status or ""
    ).strip().upper()

    if normalized_active_status == "ACTIVE":
        query = query.filter(
            Article.is_active.is_(True)
        )

    elif normalized_active_status == "INACTIVE":
        query = query.filter(
            Article.is_active.is_(False)
        )

    return (
        query
        .order_by(
            Article.created_at.desc(),
            Article.id.desc(),
        )
        .paginate(
            page=safe_page,
            per_page=safe_per_page,
            error_out=False,
        )
    )


# =========================================================
# CREACIÓN MANUAL DE ARTÍCULO
# =========================================================
def create_manual_article_code(
    *,
    code: str,
    name: str,
    unit_id: int,
    category_mode: str,
    selected_category_id: int | None,
    selected_subcategory_id: int | None,
    new_category_code: str | None,
    new_category_name: str | None,
    new_category_description: str | None,
    description: str | None,
    family_code: str | None,
    barcode: str | None,
    sap_code: str | None,
    is_tool: bool,
    is_active: bool,
    created_by_user_id: int,
    commit: bool = True,
) -> Article:
    """
    Crea un artículo sin modificar inventario, existencias ni kardex.

    Si se solicita una categoría nueva, la categoría y el artículo
    se crean dentro de la misma transacción.
    """

    normalized_code = (
        code or ""
    ).strip().upper()

    normalized_name = (
        name or ""
    ).strip()

    normalized_description = (
        description or ""
    ).strip() or None

    normalized_family_code = (
        family_code or ""
    ).strip().upper() or None

    normalized_barcode = (
        barcode or ""
    ).strip() or None

    normalized_sap_code = (
        sap_code or ""
    ).strip().upper() or None

    normalized_category_mode = (
        category_mode or "EXISTING"
    ).strip().upper()

    if not normalized_code:
        raise ArticleCodeServiceError(
            "El código del artículo es obligatorio."
        )

    if len(normalized_code) > 50:
        raise ArticleCodeServiceError(
            "El código del artículo no puede superar 50 caracteres."
        )

    if not normalized_name:
        raise ArticleCodeServiceError(
            "El nombre del artículo es obligatorio."
        )

    if not unit_id:
        raise ArticleCodeServiceError(
            "Debe seleccionar una unidad."
        )

    if not created_by_user_id:
        raise ArticleCodeServiceError(
            "No se pudo identificar al usuario creador."
        )

    # =====================================================
    # VALIDAR CÓDIGO DE ARTÍCULO
    # =====================================================
    existing_article = (
        db.session.query(Article.id)
        .filter(
            db.func.lower(Article.code)
            == normalized_code.lower()
        )
        .first()
    )

    if existing_article:
        raise ArticleCodeServiceError(
            f"Ya existe un artículo con el código {normalized_code}."
        )

    # =====================================================
    # VALIDAR CÓDIGO DE BARRAS
    # =====================================================
    if normalized_barcode:
        existing_barcode = (
            db.session.query(Article.id)
            .filter(
                Article.barcode
                == normalized_barcode
            )
            .first()
        )

        if existing_barcode:
            raise ArticleCodeServiceError(
                "Ya existe otro artículo con ese código de barras."
            )

    # =====================================================
    # VALIDAR UNIDAD
    # =====================================================
    unit_exists = (
        db.session.query(Unit.id)
        .filter(
            Unit.id == int(unit_id)
        )
        .first()
    )

    if not unit_exists:
        raise ArticleCodeServiceError(
            "La unidad seleccionada no existe."
        )

    category_id = None
    subcategory_id = None
    created_category = None

    try:
        # =================================================
        # CREAR CATEGORÍA NUEVA
        # =================================================
        if normalized_category_mode == "NEW":
            normalized_new_category_code = (
                new_category_code or ""
            ).strip().upper()

            normalized_new_category_name = (
                new_category_name or ""
            ).strip()

            normalized_new_category_description = (
                new_category_description or ""
            ).strip() or None

            if not normalized_new_category_code:
                raise ArticleCodeServiceError(
                    "El código de la nueva categoría es obligatorio."
                )

            if len(normalized_new_category_code) > 50:
                raise ArticleCodeServiceError(
                    "El código de categoría no puede superar 50 caracteres."
                )

            if not normalized_new_category_name:
                raise ArticleCodeServiceError(
                    "El nombre de la nueva categoría es obligatorio."
                )

            if len(normalized_new_category_name) > 120:
                raise ArticleCodeServiceError(
                    "El nombre de categoría no puede superar 120 caracteres."
                )

            category_by_code = (
                db.session.query(ItemCategory.id)
                .filter(
                    db.func.lower(ItemCategory.code)
                    == normalized_new_category_code.lower()
                )
                .first()
            )

            if category_by_code:
                raise ArticleCodeServiceError(
                    "Ya existe una categoría con ese código."
                )

            category_by_name = (
                db.session.query(ItemCategory.id)
                .filter(
                    db.func.lower(ItemCategory.name)
                    == normalized_new_category_name.lower()
                )
                .first()
            )

            if category_by_name:
                raise ArticleCodeServiceError(
                    "Ya existe una categoría con ese nombre."
                )

            created_category = ItemCategory(
                code=normalized_new_category_code,
                name=normalized_new_category_name,
                description=(
                    normalized_new_category_description
                ),
            )

            db.session.add(created_category)
            db.session.flush()

            category_id = created_category.id
            subcategory_id = None

        # =================================================
        # USAR CATEGORÍA EXISTENTE
        # =================================================
        elif normalized_category_mode == "EXISTING":
            if not selected_category_id:
                raise ArticleCodeServiceError(
                    "Debe seleccionar una categoría."
                )

            category = db.session.get(
                ItemCategory,
                int(selected_category_id),
            )

            if not category:
                raise ArticleCodeServiceError(
                    "La categoría seleccionada no existe."
                )

            category_id = category.id

            # =============================================
            # VALIDAR SUBCATEGORÍA OPCIONAL
            # =============================================
            if selected_subcategory_id:
                subcategory = db.session.get(
                    ItemSubcategory,
                    int(selected_subcategory_id),
                )

                if not subcategory:
                    raise ArticleCodeServiceError(
                        "La subcategoría seleccionada no existe."
                    )

                if not subcategory.is_active:
                    raise ArticleCodeServiceError(
                        "La subcategoría seleccionada está inactiva."
                    )

                if int(subcategory.category_id) != int(category_id):
                    raise ArticleCodeServiceError(
                        "La subcategoría no pertenece a la categoría seleccionada."
                    )

                subcategory_id = subcategory.id

        else:
            raise ArticleCodeServiceError(
                "El modo de categoría seleccionado no es válido."
            )

        # =================================================
        # CREAR ARTÍCULO
        # =================================================
        article = Article(
            code=normalized_code,
            name=normalized_name,
            description=normalized_description,
            category_id=category_id,
            subcategory_id=subcategory_id,
            unit_id=int(unit_id),
            family_code=normalized_family_code,
            barcode=normalized_barcode,
            sap_code=normalized_sap_code,
            is_tool=bool(is_tool),
            is_active=bool(is_active),
            creation_source="MANUAL",
            created_by_user_id=int(
                created_by_user_id
            ),
        )

        db.session.add(article)
        db.session.flush()

        # =================================================
        # AUDITORÍA
        # =================================================
        log_action(
            user_id=created_by_user_id,
            action="CREATE_ARTICLE_CODE",
            table_name="articles",
            record_id=str(article.id),
            details={
                "code": article.code,
                "name": article.name,
                "unit_id": article.unit_id,
                "category_id": article.category_id,
                "subcategory_id": article.subcategory_id,
                "family_code": article.family_code,
                "barcode": article.barcode,
                "sap_code": article.sap_code,
                "is_tool": article.is_tool,
                "is_active": article.is_active,
                "creation_source": article.creation_source,
                "created_category_id": (
                    created_category.id
                    if created_category
                    else None
                ),
            },
            commit=False,
        )

        if commit:
            db.session.commit()

        return article

    except ArticleCodeServiceError:
        if commit:
            db.session.rollback()
        raise

    except IntegrityError as exc:
        if commit:
            db.session.rollback()

        raise ArticleCodeServiceError(
            "No se pudo crear el artículo porque existe un valor duplicado."
        ) from exc

    except Exception:
        if commit:
            db.session.rollback()
        raise