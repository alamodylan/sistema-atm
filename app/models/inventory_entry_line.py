from datetime import datetime, UTC
from app.extensions import db


class InventoryEntryLine(db.Model):
    __tablename__ = "inventory_entry_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    inventory_entry_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.inventory_entries.id", ondelete="CASCADE"),
        nullable=False,
    )

    purchase_order_line_id = db.Column(db.BigInteger)
    article_id = db.Column(db.BigInteger, db.ForeignKey("atm.articles.id"))
    pending_article_id = db.Column(db.BigInteger)

    warehouse_location_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouse_locations.id"),
    )

    quantity_received = db.Column(db.Numeric(14, 2), nullable=False)

    unit_id = db.Column(db.BigInteger, db.ForeignKey("atm.units.id"))

    unit_cost_without_tax = db.Column(db.Numeric(14, 4), nullable=False, default=0)
    unit_cost_with_tax = db.Column(db.Numeric(14, 4), nullable=False, default=0)

    discount_pct = db.Column(db.Numeric(7, 4), nullable=False, default=0)
    tax_pct = db.Column(db.Numeric(7, 4), nullable=False, default=0)

    line_notes = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    inventory_entry = db.relationship(
        "InventoryEntry",
        back_populates="lines",
    )

    article = db.relationship("Article")
    warehouse_location = db.relationship("WarehouseLocation")