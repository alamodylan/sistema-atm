from datetime import UTC, datetime

from app.extensions import db


class ArticleQuotationCategory(db.Model):
    __tablename__ = "article_quotation_categories"
    __table_args__ = (
        db.CheckConstraint(
            """
            (
                article_id IS NOT NULL
                AND pending_article_id IS NULL
            )
            OR
            (
                article_id IS NULL
                AND pending_article_id IS NOT NULL
            )
            """,
            name="ck_article_quotation_categories_single_item",
        ),
        db.UniqueConstraint(
            "article_id",
            name="uq_article_quotation_categories_article",
        ),
        db.UniqueConstraint(
            "pending_article_id",
            name="uq_article_quotation_categories_pending_article",
        ),
        {"schema": "atm"},
    )

    id = db.Column(
        db.BigInteger,
        primary_key=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "atm.articles.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )

    pending_article_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "atm.pending_articles.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )

    quotation_category_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "atm.quotation_categories.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    quotation_category = db.relationship(
        "QuotationCategory",
        lazy="joined",
    )