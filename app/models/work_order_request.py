from app.extensions import db


class WorkOrderRequest(db.Model):
    __tablename__ = "work_order_requests"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    work_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    requested_by_user_id = db.Column(
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

    sent_to_warehouse_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    request_status = db.Column(
        db.String(20),
        nullable=False,
        default="ABIERTA",
        index=True,
    )
    # Valores oficiales:
    # ABIERTA, ENVIADA, ATENDIDA, CANCELADA

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    approved_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True,
    )

    sent_to_warehouse_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True,
    )

    work_order = db.relationship(
        "WorkOrder",
        back_populates="requests",
    )

    requested_by_user = db.relationship(
        "User",
        foreign_keys=[requested_by_user_id],
        back_populates="work_order_requests",
    )

    approved_by_user = db.relationship(
        "User",
        foreign_keys=[approved_by_user_id],
    )

    sent_to_warehouse_by_user = db.relationship(
        "User",
        foreign_keys=[sent_to_warehouse_by_user_id],
    )

    lines = db.relationship(
        "WorkOrderRequestLine",
        back_populates="work_order_request",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<WorkOrderRequest id={self.id} status={self.request_status}>"