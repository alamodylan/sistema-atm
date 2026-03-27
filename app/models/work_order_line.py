from datetime import datetime, UTC

from app.extensions import db


class WorkOrderLine(db.Model):
    __tablename__ = "work_order_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    work_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    request_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_order_request_lines.id"),
        nullable=True,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    quantity = db.Column(db.Numeric(14, 2), nullable=False)

    delivered_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    received_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    line_status = db.Column(
        db.String(30),
        nullable=False,
        default="ACTIVE",
        index=True,
    )
    # Valores oficiales:
    # ACTIVE, REMOVAL_PENDING, REMOVED

    inventory_posted = db.Column(db.Boolean, nullable=False, default=True)

    notes = db.Column(db.Text, nullable=True)

    delivered_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    received_at = db.Column(db.DateTime(timezone=True), nullable=True)

    work_order = db.relationship("WorkOrder", back_populates="lines")

    article = db.relationship("Article", back_populates="work_order_lines")

    request_line = db.relationship(
        "WorkOrderRequestLine",
        back_populates="delivered_lines",
    )

    delivered_by_user = db.relationship(
        "User",
        foreign_keys=[delivered_by_user_id],
        back_populates="delivered_work_order_lines",
    )

    received_by_user = db.relationship(
        "User",
        foreign_keys=[received_by_user_id],
        back_populates="received_work_order_lines",
    )

    delete_requests = db.relationship(
        "WorkOrderLineDeleteRequest",
        back_populates="work_order_line",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    waste_act_lines = db.relationship(
        "WasteActLine",
        back_populates="work_order_line",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkOrderLine "
            f"wo={self.work_order_id} article={self.article_id} qty={self.quantity}>"
        )