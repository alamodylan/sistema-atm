from app.extensions import db


class PurchaseRequest(db.Model):
    __tablename__ = "purchase_requests"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    number = db.Column(db.String(50), unique=True, nullable=False)

    requested_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
    )

    site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=True,
    )

    warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id"),
        nullable=True,
    )

    priority = db.Column(db.String(20), nullable=False, default="NORMAL")
    status = db.Column(db.String(30), nullable=False, default="BORRADOR")

    notes = db.Column(db.Text)

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

    requested_by_user = db.relationship("User")
    site = db.relationship("Site", back_populates="purchase_requests")
    warehouse = db.relationship("Warehouse")

    lines = db.relationship(
        "PurchaseRequestLine",
        back_populates="purchase_request",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    quotation_batches = db.relationship(
        "QuotationBatch",
        back_populates="purchase_request",
        lazy="selectin",
    )

    purchase_orders = db.relationship(
        "PurchaseOrder",
        back_populates="purchase_request",
        lazy="selectin",
    )