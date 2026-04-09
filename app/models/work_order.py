from datetime import datetime, UTC

from app.extensions import db


work_order_mechanics = db.Table(
    "work_order_mechanics",
    db.Column(
        "work_order_id",
        db.BigInteger,
        db.ForeignKey("atm.work_orders.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "mechanic_id",
        db.BigInteger,
        db.ForeignKey("atm.mechanics.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema="atm",
)


class WorkOrder(db.Model):
    __tablename__ = "work_orders"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    status = db.Column(db.String(20), nullable=False, default="EN_PROCESO", index=True)
    # Valores oficiales:
    # EN_PROCESO, FINALIZADA, CERRADA

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

    responsible_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
        index=True,
    )

    created_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
        index=True,
    )

    equipment_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.equipment.id"),
        nullable=True,
        index=True,
    )

    equipment_code_snapshot = db.Column(db.String(100), nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    finalized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    site = db.relationship("Site", back_populates="work_orders")
    warehouse = db.relationship("Warehouse", back_populates="work_orders")

    responsible_user = db.relationship(
        "User",
        foreign_keys=[responsible_user_id],
        back_populates="responsible_work_orders",
    )

    created_by_user = db.relationship(
        "User",
        foreign_keys=[created_by_user_id],
        back_populates="created_work_orders",
    )

    equipment = db.relationship("Equipment", back_populates="work_orders")

    lines = db.relationship(
        "WorkOrderLine",
        back_populates="work_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    requests = db.relationship(
        "WorkOrderRequest",
        back_populates="work_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    services = db.relationship(
        "WorkOrderService",
        back_populates="work_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    tool_loans = db.relationship(
        "ToolLoan",
        back_populates="work_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    waste_act_lines = db.relationship(
        "WasteActLine",
        back_populates="work_order",
        lazy="selectin",
    )

    mechanics = db.relationship(
        "Mechanic",
        secondary=work_order_mechanics,
        back_populates="work_orders",
        lazy="subquery",
    )

    def __repr__(self) -> str:
        return f"<WorkOrder {self.number} - {self.status}>"