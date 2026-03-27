from datetime import datetime, UTC

from app.extensions import db


class Article(db.Model):
    __tablename__ = "articles"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)

    category_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.item_categories.id"),
        nullable=True,
        index=True,
    )

    unit_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.units.id"),
        nullable=False,
        index=True,
    )

    family_code = db.Column(db.String(20), nullable=True, index=True)
    barcode = db.Column(db.String(100), unique=True, nullable=True, index=True)
    sap_code = db.Column(db.String(100), nullable=True, index=True)

    is_tool = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
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

    category = db.relationship("ItemCategory", back_populates="articles")
    unit = db.relationship("Unit", back_populates="articles")
    created_by_user = db.relationship("User")

    work_order_lines = db.relationship(
        "WorkOrderLine",
        back_populates="article",
        lazy="dynamic",
    )

    waste_act_lines = db.relationship(
        "WasteActLine",
        back_populates="article",
        lazy="dynamic",
    )

    work_order_request_lines = db.relationship(
        "WorkOrderRequestLine",
        back_populates="article",
        lazy="dynamic",
    )

    tool_loans = db.relationship(
        "ToolLoan",
        back_populates="article",
        lazy="dynamic",
    )

    inventory_ledger_entries = db.relationship(
        "InventoryLedger",
        back_populates="article",
        lazy="dynamic",
    )

    warehouse_stock_items = db.relationship(
        "WarehouseStock",
        back_populates="article",
        lazy="dynamic",
    )

    warehouse_location_stock_items = db.relationship(
        "WarehouseLocationStock",
        back_populates="article",
        lazy="dynamic",
    )

    physical_inventory_lines = db.relationship(
        "PhysicalInventoryLine",
        back_populates="article",
        lazy="dynamic",
    )

    transfer_request_lines = db.relationship(
        "TransferRequestLine",
        back_populates="article",
        lazy="dynamic",
    )

    transfer_lines = db.relationship(
        "TransferLine",
        back_populates="article",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Article {self.code} - {self.name}>"