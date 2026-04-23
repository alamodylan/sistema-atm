from datetime import UTC, datetime

from app.extensions import db


class RepairType(db.Model):
    __tablename__ = "repair_types"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    code = db.Column(db.String(50), nullable=False, unique=True, index=True)
    name = db.Column(db.String(150), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    specialty_assignments = db.relationship(
        "RepairTypeSpecialty",
        back_populates="repair_type",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    task_lines = db.relationship(
        "WorkOrderTaskLine",
        back_populates="repair_type",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<RepairType {self.code} - {self.name}>"