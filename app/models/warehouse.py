from datetime import datetime, UTC

from app.extensions import db


class Warehouse(db.Model):
    __tablename__ = "warehouses"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=False,
        index=True,
    )

    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, index=True)

    warehouse_type = db.Column(db.String(30), nullable=False, default="BODEGA", index=True)
    # Valores oficiales:
    # BODEGA, MINIBODEGA, CAJA_HERRAMIENTAS

    responsible_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    site = db.relationship("Site", back_populates="warehouses")

    responsible_user = db.relationship(
        "User",
        foreign_keys=[responsible_user_id],
    )

    created_by_user = db.relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )

    work_orders = db.relationship(
        "WorkOrder",
        back_populates="warehouse",
        lazy="dynamic",
    )

    stock_items = db.relationship(
        "WarehouseStock",
        back_populates="warehouse",
        lazy="dynamic",
    )

    ledger_entries = db.relationship(
        "InventoryLedger",
        foreign_keys="InventoryLedger.warehouse_id",
        back_populates="warehouse",
        lazy="dynamic",
    )

    related_ledger_entries = db.relationship(
        "InventoryLedger",
        foreign_keys="InventoryLedger.related_warehouse_id",
        back_populates="related_warehouse",
        lazy="dynamic",
    )

    locations = db.relationship(
        "WarehouseLocation",
        back_populates="warehouse",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    toolboxes = db.relationship(
        "Toolbox",
        back_populates="warehouse",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    transfer_requests_as_origin = db.relationship(
        "TransferRequest",
        foreign_keys="TransferRequest.origin_warehouse_id",
        back_populates="origin_warehouse",
        lazy="dynamic",
    )

    transfer_requests_as_destination = db.relationship(
        "TransferRequest",
        foreign_keys="TransferRequest.destination_warehouse_id",
        back_populates="destination_warehouse",
        lazy="dynamic",
    )

    transfers_as_origin = db.relationship(
        "Transfer",
        foreign_keys="Transfer.origin_warehouse_id",
        back_populates="origin_warehouse",
        lazy="dynamic",
    )

    transfers_as_destination = db.relationship(
        "Transfer",
        foreign_keys="Transfer.destination_warehouse_id",
        back_populates="destination_warehouse",
        lazy="dynamic",
    )

    physical_inventories = db.relationship(
        "PhysicalInventory",
        back_populates="warehouse",
        lazy="dynamic",
    )

    waste_acts = db.relationship(
        "WasteAct",
        back_populates="warehouse",
        lazy="dynamic",
    )

    tool_loans = db.relationship(
        "ToolLoan",
        back_populates="warehouse",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Warehouse {self.code} - {self.name}>"