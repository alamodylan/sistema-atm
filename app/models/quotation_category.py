from datetime import UTC, datetime

from app.extensions import db


class QuotationCategory(db.Model):
    __tablename__ = "quotation_categories"
    __table_args__ = (
        db.UniqueConstraint(
            "name",
            name="uq_quotation_categories_name",
        ),
        db.CheckConstraint(
            "sort_order > 0",
            name="ck_quotation_categories_sort_order_positive",
        ),
        {"schema": "atm"},
    )

    id = db.Column(
        db.BigInteger,
        primary_key=True,
    )

    name = db.Column(
        db.String(100),
        nullable=False,
    )

    sort_order = db.Column(
        db.Integer,
        nullable=False,
        default=1,
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
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