from app.extensions import db


class PendingArticle(db.Model):
    __tablename__ = "pending_articles"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    provisional_code = db.Column(db.String(80), unique=True, nullable=True)
    provisional_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    category_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.item_categories.id"),
        nullable=True,
    )

    unit_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.units.id"),
        nullable=True,
    )

    requested_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="PENDIENTE_CODIFICACION",
    )

    linked_article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    category = db.relationship("ItemCategory")
    unit = db.relationship("Unit")
    requested_by_user = db.relationship("User")
    linked_article = db.relationship("Article")

    purchase_request_lines = db.relationship(
        "PurchaseRequestLine",
        back_populates="pending_article",
        lazy="selectin",
    )

    quotation_lines = db.relationship(
        "QuotationLine",
        back_populates="pending_article",
        lazy="selectin",
    )

    purchase_order_lines = db.relationship(
        "PurchaseOrderLine",
        back_populates="pending_article",
        lazy="selectin",
    )

    inventory_entry_lines = db.relationship(
        "InventoryEntryLine",
        back_populates="pending_article",
        lazy="selectin",
    )

    @property
    def is_resolved(self) -> bool:
        return self.status == "CODIFICADO" and self.linked_article_id is not None