from app.extensions import db


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    number = db.Column(db.String(50), unique=True, nullable=False)

    purchase_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.purchase_requests.id"),
        nullable=True,
    )

    supplier_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.suppliers.id"),
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

    generated_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
    )

    approval_status = db.Column(db.String(30), nullable=False, default="BORRADOR")
    payment_terms = db.Column(db.String(100))
    currency_code = db.Column(db.String(10), nullable=False, default="CRC")
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

    purchase_request = db.relationship(
        "PurchaseRequest",
        back_populates="purchase_orders",
    )

    supplier = db.relationship("Supplier")
    site = db.relationship("Site", back_populates="purchase_orders")
    warehouse = db.relationship("Warehouse")
    generated_by_user = db.relationship("User")

    lines = db.relationship(
        "PurchaseOrderLine",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    approvals = db.relationship(
        "PurchaseOrderApproval",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    inventory_entries = db.relationship(
        "InventoryEntry",
        back_populates="purchase_order",
        lazy="selectin",
    )