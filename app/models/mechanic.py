from datetime import UTC, datetime

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class Mechanic(db.Model):
    __tablename__ = "mechanics"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=False,
        index=True,
    )

    code = db.Column(db.String(50), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False, index=True)

    pin_hash = db.Column(
        db.String(255),
        nullable=True,
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
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

    site = db.relationship("Site")

    work_orders = db.relationship(
        "WorkOrder",
        secondary="atm.work_order_mechanics",
        back_populates="mechanics",
        lazy="subquery",
    )

    specialty_assignments = db.relationship(
        "MechanicSpecialtyAssignment",
        back_populates="mechanic",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    task_lines_assigned = db.relationship(
        "WorkOrderTaskLine",
        foreign_keys="WorkOrderTaskLine.assigned_mechanic_id",
        back_populates="assigned_mechanic",
        lazy="selectin",
    )

    task_line_assignments = db.relationship(
        "WorkOrderTaskLineAssignment",
        back_populates="mechanic",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    task_line_finish_requests = db.relationship(
        "WorkOrderTaskLineFinishRequest",
        foreign_keys="WorkOrderTaskLineFinishRequest.requested_by_mechanic_id",
        back_populates="requested_by_mechanic",
        lazy="selectin",
    )

    def set_pin(self, pin: str | None) -> None:
        normalized_pin = (pin or "").strip()

        if not normalized_pin:
            self.pin_hash = None
            return

        if not normalized_pin.isdigit() or len(normalized_pin) != 4:
            raise ValueError("El PIN debe contener exactamente 4 dígitos.")

        self.pin_hash = generate_password_hash(normalized_pin)

    def check_pin(self, pin: str | None) -> bool:
        normalized_pin = (pin or "").strip()

        if not self.pin_hash:
            return False

        if not normalized_pin.isdigit() or len(normalized_pin) != 4:
            return False

        return check_password_hash(self.pin_hash, normalized_pin)

    @property
    def has_pin(self) -> bool:
        return bool(self.pin_hash)

    def __repr__(self) -> str:
        return f"<Mechanic site={self.site_id} code={self.code} - {self.name}>"