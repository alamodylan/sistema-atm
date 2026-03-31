from app.extensions import db


class PurchaseRequestLine(db.Model):
    __tablename__ = "purchase_request_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    purchase_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.purchase_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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

    quantity_requested = db.Column(db.Numeric(14, 2), nullable=False)

    unit_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.units.id"),
        nullable=True,
    )

    line_notes = db.Column(db.Text)

    is_urgent = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )

    line_status = db.Column(
        db.String(30),
        nullable=False,
        default="ACTIVA",
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    purchase_request = db.relationship(
        "PurchaseRequest",
        back_populates="lines",
    )

    article = db.relationship("Article")

    pending_article = db.relationship(
        "PendingArticle",
        back_populates="purchase_request_lines",
    )

    unit = db.relationship("Unit")

    quotation_lines = db.relationship(
        "QuotationLine",
        back_populates="purchase_request_line",
        lazy="selectin",
    )

    purchase_order_lines = db.relationship(
        "PurchaseOrderLine",
        back_populates="purchase_request_line",
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
    def is_pending(self) -> bool:
        return self.pending_article_id is not None