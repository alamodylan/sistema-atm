# models/deletion_request.py
from datetime import datetime, UTC

from app.extensions import db


class WorkOrderLineDeleteRequest(db.Model):
    __tablename__ = "work_order_line_delete_requests"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    work_order_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_order_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    requested_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
        index=True,
    )

    reviewed_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="PENDIENTE",
        index=True,
    )
    # Valores oficiales:
    # PENDIENTE, APROBADA, RECHAZADA

    reason = db.Column(db.Text, nullable=False)
    review_notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    work_order_line = db.relationship(
        "WorkOrderLine",
        back_populates="delete_requests",
    )

    requested_by_user = db.relationship(
        "User",
        foreign_keys=[requested_by_user_id],
        back_populates="requested_delete_requests",
    )

    reviewed_by_user = db.relationship(
        "User",
        foreign_keys=[reviewed_by_user_id],
        back_populates="reviewed_delete_requests",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkOrderLineDeleteRequest "
            f"line={self.work_order_line_id} status={self.status}>"
        )