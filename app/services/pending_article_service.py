from __future__ import annotations

from sqlalchemy import func

from app.extensions import db
from app.models.article import Article
from app.models.article_supplier import ArticleSupplier
from app.models.pending_article import PendingArticle
from app.models.quotation_line import QuotationLine


class PendingArticleServiceError(Exception):
    pass


def _generate_provisional_code() -> str:
    max_id = db.session.query(func.max(PendingArticle.id)).scalar() or 0
    return f"PEND-{int(max_id) + 1:06d}"


def _ensure_article_supplier(
    *,
    article_id: int | None,
    supplier_id: int | None,
) -> None:
    if not article_id or not supplier_id:
        return

    existing = (
        ArticleSupplier.query
        .filter(
            ArticleSupplier.article_id == article_id,
            ArticleSupplier.supplier_id == supplier_id,
        )
        .first()
    )

    if existing:
        existing.is_active = True
        existing.updated_at = db.func.now()
        return

    db.session.add(
        ArticleSupplier(
            article_id=article_id,
            supplier_id=supplier_id,
            is_active=True,
        )
    )


def _link_suppliers_from_pending_article(
    *,
    pending_article_id: int,
    linked_article_id: int,
) -> None:
    supplier_rows = (
        db.session.query(QuotationLine.supplier_id)
        .filter(
            QuotationLine.pending_article_id == pending_article_id,
            QuotationLine.supplier_id.isnot(None),
            QuotationLine.status != "DESCARTADA",
        )
        .distinct()
        .all()
    )

    for row in supplier_rows:
        _ensure_article_supplier(
            article_id=linked_article_id,
            supplier_id=row.supplier_id,
        )


def create_pending_article(
    *,
    provisional_name: str,
    description: str | None,
    category_id: int | None,
    unit_id: int | None,
    requested_by_user_id: int | None,
) -> PendingArticle:
    provisional_name = (provisional_name or "").strip()

    if not provisional_name:
        raise PendingArticleServiceError("El nombre provisional es obligatorio.")

    pending_article = PendingArticle(
        provisional_code=_generate_provisional_code(),
        provisional_name=provisional_name,
        description=(description or "").strip() or None,
        category_id=category_id,
        unit_id=unit_id,
        requested_by_user_id=requested_by_user_id,
        status="PENDIENTE_CODIFICACION",
    )

    db.session.add(pending_article)
    db.session.commit()

    return pending_article


def list_pending_articles(
    *,
    status: str | None = None,
    search: str | None = None,
) -> list[PendingArticle]:
    query = PendingArticle.query

    if status:
        query = query.filter(PendingArticle.status == status)

    if search:
        like_value = f"%{search.strip()}%"
        query = query.filter(
            db.or_(
                PendingArticle.provisional_code.ilike(like_value),
                PendingArticle.provisional_name.ilike(like_value),
            )
        )

    return query.order_by(
        PendingArticle.created_at.desc(),
        PendingArticle.id.desc(),
    ).all()


def get_pending_article_or_404(pending_article_id: int) -> PendingArticle:
    return PendingArticle.query.get_or_404(pending_article_id)


def resolve_pending_article(
    *,
    pending_article_id: int,
    final_code: str,
    final_name: str,
) -> PendingArticle:
    pending_article = get_pending_article_or_404(pending_article_id)

    if pending_article.status == "CANCELADO":
        raise PendingArticleServiceError(
            "No se puede resolver un artículo pendiente cancelado."
        )

    final_code = (final_code or "").strip()
    final_name = (final_name or "").strip()

    if not final_code:
        raise PendingArticleServiceError(
            "Debes indicar el código definitivo de 5 dígitos."
        )

    if not final_code.isdigit() or len(final_code) != 5:
        raise PendingArticleServiceError(
            "El código definitivo debe tener exactamente 5 dígitos."
        )

    if not final_name:
        raise PendingArticleServiceError(
            "Debes indicar el nombre definitivo del artículo."
        )

    if not pending_article.linked_article_id:
        raise PendingArticleServiceError(
            "El artículo pendiente no tiene un artículo provisional enlazado para actualizar."
        )

    linked_article = Article.query.get(pending_article.linked_article_id)

    if not linked_article:
        raise PendingArticleServiceError(
            "El artículo enlazado del pendiente no existe."
        )

    existing_article = Article.query.filter(
        Article.code == final_code,
        Article.id != linked_article.id,
    ).first()

    if existing_article:
        raise PendingArticleServiceError(
            "Ya existe otro artículo con ese código definitivo."
        )

    linked_article.code = final_code
    linked_article.name = final_name

    _link_suppliers_from_pending_article(
        pending_article_id=pending_article.id,
        linked_article_id=linked_article.id,
    )

    pending_article.status = "CODIFICADO"

    db.session.commit()

    return pending_article