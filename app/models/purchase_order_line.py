from app.extensions import db


class PurchaseOrderLine(db.Model):
    __tablename__ = "purchase_order_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    purchase_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )

    purchase_request_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.purchase_request_lines.id"),
        nullable=True,
    )

    quotation_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.quotation_lines.id"),
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

    quantity_ordered = db.Column(db.Numeric(14, 2), nullable=False)
    quantity_received = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    unit_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.units.id"),
        nullable=True,
    )

    unit_cost = db.Column(db.Numeric(14, 4), nullable=False, default=0)
    discount_pct = db.Column(db.Numeric(7, 4), nullable=False, default=0)
    tax_pct = db.Column(db.Numeric(7, 4), nullable=False, default=0)
    line_subtotal = db.Column(db.Numeric(14, 4), nullable=False, default=0)
    line_total = db.Column(db.Numeric(14, 4), nullable=False, default=0)

    line_notes = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    purchase_order = db.relationship(
        "PurchaseOrder",
        back_populates="lines",
    )

    purchase_request_line = db.relationship(
        "PurchaseRequestLine",
        back_populates="purchase_order_lines",
    )

    quotation_line = db.relationship(
        "QuotationLine",
        back_populates="purchase_order_lines",
    )

    article = db.relationship("Article")

    pending_article = db.relationship(
        "PendingArticle",
        back_populates="purchase_order_lines",
    )

    unit = db.relationship("Unit")

    inventory_entry_lines = db.relationship(
        "InventoryEntryLine",
        back_populates="purchase_order_line",
        lazy="selectin",
    )

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

    @property
    def pending_quantity(self):
        return max((self.quantity_ordered or 0) - (self.quantity_received or 0), 0)

    @property
    def is_fully_received(self) -> bool:
        return (self.quantity_received or 0) >= (self.quantity_ordered or 0)