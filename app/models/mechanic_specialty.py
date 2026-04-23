from datetime import UTC, datetime

from app.extensions import db


class MechanicSpecialty(db.Model):
    __tablename__ = "mechanic_specialties"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    code = db.Column(db.String(50), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    mechanic_assignments = db.relationship(
        "MechanicSpecialtyAssignment",
        back_populates="specialty",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    task_lines = db.relationship(
        "WorkOrderTaskLine",
        back_populates="specialty",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<MechanicSpecialty {self.code} - {self.name}>"