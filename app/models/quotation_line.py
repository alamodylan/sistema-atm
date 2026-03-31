from app.extensions import db


class QuotationLine(db.Model):
    __tablename__ = "quotation_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    quotation_batch_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.quotation_batches.id", ondelete="CASCADE"),
        nullable=False,
    )

    purchase_request_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.purchase_request_lines.id"),
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

    supplier_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.suppliers.id"),
        nullable=False,
    )

    quote_date = db.Column(db.Date, nullable=False)

    currency_code = db.Column(
        db.String(10),
        nullable=False,
        default="CRC",
    )

    unit_price = db.Column(db.Numeric(14, 4), nullable=False)

    discount_pct = db.Column(
        db.Numeric(7, 4),
        nullable=False,
        default=0,
    )

    tax_pct = db.Column(
        db.Numeric(7, 4),
        nullable=False,
        default=0,
    )

    tax_included = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )

    lead_time_days = db.Column(db.Integer, nullable=True)
    brand_model = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    quotation_batch = db.relationship(
        "QuotationBatch",
        back_populates="lines",
    )

    purchase_request_line = db.relationship(
        "PurchaseRequestLine",
        back_populates="quotation_lines",
    )

    article = db.relationship("Article")

    pending_article = db.relationship(
        "PendingArticle",
        back_populates="quotation_lines",
    )

    supplier = db.relationship("Supplier")

    purchase_order_lines = db.relationship(
        "PurchaseOrderLine",
        back_populates="quotation_line",
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
    def unit_price_with_tax(self):
        if self.tax_included:
            return self.unit_price
        return self.unit_price * (1 + (self.tax_pct or 0) / 100)

    @property
    def unit_price_net(self):
        price = self.unit_price
        if self.discount_pct:
            price = price * (1 - self.discount_pct / 100)
        return price