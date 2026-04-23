from datetime import UTC, datetime

from app.extensions import db


class WorkOrderTaskLineAssignment(db.Model):
    __tablename__ = "work_order_task_line_assignments"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    task_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_order_task_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    mechanic_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.mechanics.id"),
        nullable=False,
        index=True,
    )

    started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)

    seconds_worked = db.Column(db.BigInteger, nullable=False, default=0)

    ended_reason = db.Column(db.String(40), nullable=True)
    # Valores oficiales:
    # REASIGNADO, FINALIZACION_SOLICITADA, PAUSA_JEFATURA, FINALIZADO, DESESTIMADO_REANUDADO

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    task_line = db.relationship(
        "WorkOrderTaskLine",
        back_populates="assignments",
    )

    mechanic = db.relationship(
        "Mechanic",
        back_populates="task_line_assignments",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkOrderTaskLineAssignment "
            f"task_line={self.task_line_id} mechanic={self.mechanic_id}>"
        )