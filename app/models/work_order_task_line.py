from datetime import UTC, datetime

from app.extensions import db


class WorkOrderTaskLine(db.Model):
    __tablename__ = "work_order_task_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    work_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    specialty_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.mechanic_specialties.id"),
        nullable=False,
        index=True,
    )

    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.String(40),
        nullable=False,
        default="PENDIENTE",
        index=True,
    )
    # Valores oficiales:
    # PENDIENTE, EN_PROCESO, PAUSADA, FINALIZACION_SOLICITADA, FINALIZADA, CANCELADA

    assigned_mechanic_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.mechanics.id"),
        nullable=True,
        index=True,
    )

    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    paused_at = db.Column(db.DateTime(timezone=True), nullable=True)

    effective_seconds = db.Column(db.BigInteger, nullable=False, default=0)

    finish_requested_at = db.Column(db.DateTime(timezone=True), nullable=True)
    approved_finished_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
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

    work_order = db.relationship(
        "WorkOrder",
        back_populates="task_lines",
    )

    specialty = db.relationship(
        "MechanicSpecialty",
        back_populates="task_lines",
    )

    assigned_mechanic = db.relationship(
        "Mechanic",
        foreign_keys=[assigned_mechanic_id],
        back_populates="task_lines_assigned",
    )

    created_by_user = db.relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )

    assignments = db.relationship(
        "WorkOrderTaskLineAssignment",
        back_populates="task_line",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    finish_requests = db.relationship(
        "WorkOrderTaskLineFinishRequest",
        back_populates="task_line",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkOrderTaskLine "
            f"wo={self.work_order_id} specialty={self.specialty_id} status={self.status}>"
        )