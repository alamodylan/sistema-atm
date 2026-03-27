from datetime import datetime, UTC

from app.extensions import db


class Site(db.Model):
    __tablename__ = "sites"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    warehouses = db.relationship(
        "Warehouse",
        back_populates="site",
        lazy="dynamic",
    )

    work_orders = db.relationship(
        "WorkOrder",
        back_populates="site",
        lazy="dynamic",
    )

    waste_acts = db.relationship(
        "WasteAct",
        back_populates="site",
        lazy="dynamic",
    )

    physical_inventories = db.relationship(
        "PhysicalInventory",
        back_populates="site",
        lazy="dynamic",
    )

    inventory_entries = db.relationship(
        "InventoryEntry",
        back_populates="site",
        lazy="dynamic",
    )

    purchase_orders = db.relationship(
        "PurchaseOrder",
        back_populates="site",
        lazy="dynamic",
    )

    purchase_requests = db.relationship(
        "PurchaseRequest",
        back_populates="site",
        lazy="dynamic",
    )

    transfer_requests_as_origin = db.relationship(
        "TransferRequest",
        foreign_keys="TransferRequest.origin_site_id",
        back_populates="origin_site",
        lazy="dynamic",
    )

    transfer_requests_as_destination = db.relationship(
        "TransferRequest",
        foreign_keys="TransferRequest.destination_site_id",
        back_populates="destination_site",
        lazy="dynamic",
    )

    transfers_as_origin = db.relationship(
        "Transfer",
        foreign_keys="Transfer.origin_site_id",
        back_populates="origin_site",
        lazy="dynamic",
    )

    transfers_as_destination = db.relationship(
        "Transfer",
        foreign_keys="Transfer.destination_site_id",
        back_populates="destination_site",
        lazy="dynamic",
    )

    user_access = db.relationship(
        "UserSiteAccess",
        back_populates="site",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Site {self.code} - {self.name}>"