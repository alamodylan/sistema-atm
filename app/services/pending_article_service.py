from __future__ import annotations

from sqlalchemy import func

from app.extensions import db
from app.models.pending_article import PendingArticle


class PendingArticleServiceError(Exception):
    pass


def _generate_provisional_code() -> str:
    max_id = db.session.query(func.max(PendingArticle.id)).scalar() or 0
    return f"PEND-{int(max_id) + 1:06d}"


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

    return query.order_by(PendingArticle.created_at.desc(), PendingArticle.id.desc()).all()


def get_pending_article_or_404(pending_article_id: int) -> PendingArticle:
    return PendingArticle.query.get_or_404(pending_article_id)


def resolve_pending_article(
    *,
    pending_article_id: int,
    linked_article_id: int,
) -> PendingArticle:
    pending_article = get_pending_article_or_404(pending_article_id)

    if pending_article.status == "CANCELADO":
        raise PendingArticleServiceError("No se puede resolver un artículo pendiente cancelado.")

    pending_article.linked_article_id = linked_article_id
    pending_article.status = "CODIFICADO"

    db.session.commit()
    return pending_article