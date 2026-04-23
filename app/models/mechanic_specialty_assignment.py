from datetime import UTC, datetime

from app.extensions import db


class MechanicSpecialtyAssignment(db.Model):
    __tablename__ = "mechanic_specialty_assignments"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    mechanic_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.mechanics.id", ondelete="CASCADE"),
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

    mechanic = db.relationship(
        "Mechanic",
        back_populates="specialty_assignments",
    )

    specialty = db.relationship(
        "MechanicSpecialty",
        back_populates="mechanic_assignments",
    )

    def __repr__(self) -> str:
        return (
            f"<MechanicSpecialtyAssignment "
            f"mechanic={self.mechanic_id} specialty={self.specialty_id}>"
        )