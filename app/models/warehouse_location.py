from datetime import datetime, UTC

from app.extensions import db


class WarehouseLocation(db.Model):
    __tablename__ = "warehouse_locations"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code = db.Column(db.String(80), nullable=False, index=True)
    aisle = db.Column(db.String(50), nullable=True)
    shelf = db.Column(db.String(50), nullable=True)
    level_no = db.Column(db.String(20), nullable=True)
    position_no = db.Column(db.String(20), nullable=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    warehouse = db.relationship(
        "Warehouse",
        back_populates="locations",
    )

    ledger_entries = db.relationship(
        "InventoryLedger",
        back_populates="warehouse_location",
        lazy="dynamic",
    )

    stock_items = db.relationship(
        "WarehouseLocationStock",
        back_populates="warehouse_location",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    inventory_entry_lines = db.relationship(
        "InventoryEntryLine",
        back_populates="warehouse_location",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<WarehouseLocation wh={self.warehouse_id} code={self.code}>"