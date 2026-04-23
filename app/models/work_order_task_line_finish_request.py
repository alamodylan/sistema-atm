from datetime import UTC, datetime

from app.extensions import db


class WorkOrderTaskLineFinishRequest(db.Model):
    __tablename__ = "work_order_task_line_finish_requests"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    task_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_order_task_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    requested_by_mechanic_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.mechanics.id"),
        nullable=False,
        index=True,
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="PENDIENTE",
        index=True,
    )
    # Valores oficiales:
    # PENDIENTE, APROBADA, DESESTIMADA

    request_notes = db.Column(db.Text, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)

    requested_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    reviewed_by_user_id = db.Column(
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

    task_line = db.relationship(
        "WorkOrderTaskLine",
        back_populates="finish_requests",
    )

    requested_by_mechanic = db.relationship(
        "Mechanic",
        foreign_keys=[requested_by_mechanic_id],
        back_populates="task_line_finish_requests",
    )

    reviewed_by_user = db.relationship(
        "User",
        foreign_keys=[reviewed_by_user_id],
    )

    def __repr__(self) -> str:
        return (
            f"<WorkOrderTaskLineFinishRequest "
            f"task_line={self.task_line_id} status={self.status}>"
        )