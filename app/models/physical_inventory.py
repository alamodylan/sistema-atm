from datetime import datetime, UTC

from app.extensions import db


class PhysicalInventory(db.Model):
    __tablename__ = "physical_inventories"
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
        index=True,
    )

    approved_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    status = db.Column(db.String(30), nullable=False, default="BORRADOR", index=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    adjusted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    site = db.relationship(
        "Site",
        back_populates="physical_inventories",
    )

    warehouse = db.relationship(
        "Warehouse",
        back_populates="physical_inventories",
    )

    created_by_user = db.relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )

    approved_by_user = db.relationship(
        "User",
        foreign_keys=[approved_by_user_id],
    )

    lines = db.relationship(
        "PhysicalInventoryLine",
        back_populates="physical_inventory",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<PhysicalInventory {self.number} - {self.status}>"