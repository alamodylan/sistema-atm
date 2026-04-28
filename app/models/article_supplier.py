from app.extensions import db


class ArticleSupplier(db.Model):
    __tablename__ = "article_suppliers"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    supplier_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.suppliers.id"),
        nullable=False,
        index=True,
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    article = db.relationship("Article")
    supplier = db.relationship("Supplier")