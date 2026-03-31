from datetime import UTC, datetime

from app.extensions import db


class InventoryEntry(db.Model):
    __tablename__ = "inventory_entries"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    purchase_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.purchase_orders.id"),
        nullable=False,
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
        nullable=False,
    )

    invoice_number = db.Column(db.String(100), nullable=False)
    invoice_date = db.Column(db.Date, nullable=True)

    entered_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
    )

    notes = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    site = db.relationship("Site", back_populates="inventory_entries")
    warehouse = db.relationship("Warehouse")
    purchase_order = db.relationship("PurchaseOrder", back_populates="inventory_entries")
    supplier = db.relationship("Supplier")
    entered_by_user = db.relationship("User")

    lines = db.relationship(
        "InventoryEntryLine",
        back_populates="inventory_entry",
        cascade="all, delete-orphan",
        lazy="selectin",
    )