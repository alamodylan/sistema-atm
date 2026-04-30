from datetime import UTC, datetime

from app.extensions import db


class InventoryAdjustmentLine(db.Model):
    __tablename__ = "inventory_adjustment_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    adjustment_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.inventory_adjustments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    quantity_before = db.Column(db.Numeric(14, 2), nullable=False)
    quantity_after = db.Column(db.Numeric(14, 2), nullable=False)
    difference = db.Column(db.Numeric(14, 2), nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    adjustment = db.relationship(
        "InventoryAdjustment",
        back_populates="lines",
    )

    article = db.relationship("Article")