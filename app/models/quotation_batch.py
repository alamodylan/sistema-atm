from app.extensions import db


class QuotationBatch(db.Model):
    __tablename__ = "quotation_batches"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    number = db.Column(db.String(50), unique=True, nullable=False)

    purchase_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.purchase_requests.id"),
        nullable=True,
    )

    created_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
    )

    quote_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    purchase_request = db.relationship("PurchaseRequest")
    created_by_user = db.relationship("User")

    lines = db.relationship(
        "QuotationLine",
        back_populates="quotation_batch",
        cascade="all, delete-orphan",
        lazy="selectin",
    )