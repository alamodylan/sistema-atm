from datetime import UTC, datetime

from app.extensions import db


class InventoryAdjustment(db.Model):
    __tablename__ = "inventory_adjustments"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=False,
        index=True,
    )

    warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id"),
        nullable=False,
        index=True,
    )

    created_by_user_id = db.Column(
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

    site = db.relationship("Site")
    warehouse = db.relationship("Warehouse")
    created_by_user = db.relationship("User")

    lines = db.relationship(
        "InventoryAdjustmentLine",
        back_populates="adjustment",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )