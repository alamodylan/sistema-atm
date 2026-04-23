from datetime import UTC, datetime

from app.extensions import db


class RepairTypeSpecialty(db.Model):
    __tablename__ = "repair_type_specialties"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    repair_type_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.repair_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    specialty_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.mechanic_specialties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    repair_type = db.relationship(
        "RepairType",
        back_populates="specialty_assignments",
    )

    specialty = db.relationship(
        "MechanicSpecialty",
        back_populates="repair_type_assignments",
    )

    def __repr__(self) -> str:
        return (
            f"<RepairTypeSpecialty "
            f"repair_type={self.repair_type_id} specialty={self.specialty_id}>"
        )