from datetime import datetime, UTC

from app.extensions import db


class WorkOrderService(db.Model):
    __tablename__ = "work_order_services"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    work_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    service_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.services_catalog.id"),
        nullable=False,
        index=True,
    )

    notes = db.Column(db.Text, nullable=True)

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

    # RELACIONES

    work_order = db.relationship(
        "WorkOrder",
        back_populates="services",
    )

    created_by_user = db.relationship(
        "User",
    )

    def __repr__(self) -> str:
        return f"<WorkOrderService wo={self.work_order_id} service={self.service_id}>"