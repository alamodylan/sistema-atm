from datetime import UTC, datetime

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

    purchase_order_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.purchase_order_lines.id"),
        nullable=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=True,
    )

    pending_article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.pending_articles.id"),
        nullable=True,
    )

    warehouse_location_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouse_locations.id"),
        nullable=True,
    )

    quantity_received = db.Column(db.Numeric(14, 2), nullable=False)

    unit_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.units.id"),
        nullable=True,
    )

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

    purchase_order_line = db.relationship(
        "PurchaseOrderLine",
        back_populates="inventory_entry_lines",
    )

    article = db.relationship("Article")

    pending_article = db.relationship(
        "PendingArticle",
        back_populates="inventory_entry_lines",
    )

    warehouse_location = db.relationship("WarehouseLocation")
    unit = db.relationship("Unit")

    @property
    def item_name(self) -> str:
        if self.article:
            return self.article.name
        if self.pending_article:
            return self.pending_article.provisional_name
        return "Sin artículo"

    @property
    def item_code(self) -> str:
        if self.article:
            return self.article.code
        if self.pending_article:
            return self.pending_article.provisional_code or ""
        return ""