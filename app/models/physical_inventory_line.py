from datetime import datetime, UTC

from app.extensions import db


class PhysicalInventoryLine(db.Model):
    __tablename__ = "physical_inventory_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    physical_inventory_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.physical_inventories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    system_quantity = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    physical_quantity = db.Column(db.Numeric(14, 2), nullable=True)
    difference_quantity = db.Column(db.Numeric(14, 2), nullable=True)

    counted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    physical_inventory = db.relationship(
        "PhysicalInventory",
        back_populates="lines",
    )

    article = db.relationship(
        "Article",
        back_populates="physical_inventory_lines",
    )

    def __repr__(self) -> str:
        return (
            f"<PhysicalInventoryLine inv={self.physical_inventory_id} "
            f"article={self.article_id}>"
        )