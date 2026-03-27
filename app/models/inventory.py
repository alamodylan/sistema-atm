from datetime import datetime, UTC

from app.extensions import db


class InventoryLedger(db.Model):
    __tablename__ = "inventory_ledger"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    movement_type = db.Column(db.String(50), nullable=False, index=True)
    # Valores oficiales:
    # ENTRADA_COMPRA
    # SALIDA_OT
    # PRESTAMO_HERRAMIENTA
    # DEVOLUCION_HERRAMIENTA
    # TRASLADO_SALIDA
    # TRASLADO_ENTRADA
    # AJUSTE_INVENTARIO_FISICO
    # REVERSO_ELIMINACION_LINEA_OT
    # AJUSTE_MANUAL

    warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id"),
        nullable=False,
        index=True,
    )

    related_warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id"),
        nullable=True,
        index=True,
    )

    warehouse_location_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouse_locations.id"),
        nullable=True,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    quantity_change = db.Column(db.Numeric(14, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(14, 4), nullable=True)
    total_cost = db.Column(db.Numeric(14, 4), nullable=True)

    reference_type = db.Column(db.String(50), nullable=True, index=True)
    reference_id = db.Column(db.BigInteger, nullable=True, index=True)
    reference_number = db.Column(db.String(100), nullable=True, index=True)

    notes = db.Column(db.Text, nullable=True)

    performed_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    warehouse = db.relationship(
        "Warehouse",
        foreign_keys=[warehouse_id],
        back_populates="ledger_entries",
    )

    related_warehouse = db.relationship(
        "Warehouse",
        foreign_keys=[related_warehouse_id],
        back_populates="related_ledger_entries",
    )

    article = db.relationship(
        "Article",
        back_populates="inventory_ledger_entries",
    )

    performed_by_user = db.relationship(
        "User",
        foreign_keys=[performed_by_user_id],
    )

    warehouse_location = db.relationship(
        "WarehouseLocation",
        back_populates="ledger_entries",
    )

    def __repr__(self) -> str:
        return (
            f"<InventoryLedger id={self.id} "
            f"movement={self.movement_type} article={self.article_id} "
            f"qty={self.quantity_change}>"
        )


class WarehouseStock(db.Model):
    __tablename__ = "warehouse_stock"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    quantity = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    reserved_quantity = db.Column(db.Numeric(14, 2), nullable=False, default=0)

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

    warehouse = db.relationship(
        "Warehouse",
        back_populates="stock_items",
    )

    article = db.relationship(
        "Article",
        back_populates="warehouse_stock_items",
    )

    @property
    def available_quantity(self):
        quantity = self.quantity or 0
        reserved = self.reserved_quantity or 0
        return quantity - reserved

    def __repr__(self) -> str:
        return (
            f"<WarehouseStock warehouse={self.warehouse_id} "
            f"article={self.article_id} qty={self.quantity}>"
        )


class WarehouseLocationStock(db.Model):
    __tablename__ = "warehouse_location_stock"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    warehouse_location_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouse_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    quantity = db.Column(db.Numeric(14, 2), nullable=False, default=0)

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

    warehouse_location = db.relationship(
        "WarehouseLocation",
        back_populates="stock_items",
    )

    article = db.relationship(
        "Article",
        back_populates="warehouse_location_stock_items",
    )

    def __repr__(self) -> str:
        return (
            f"<WarehouseLocationStock location={self.warehouse_location_id} "
            f"article={self.article_id} qty={self.quantity}>"
        )