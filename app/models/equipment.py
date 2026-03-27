from datetime import datetime, UTC

from app.extensions import db


class Equipment(db.Model):
    __tablename__ = "equipment"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    code = db.Column(db.String(100), unique=True, nullable=False, index=True)
    equipment_type = db.Column(db.String(50), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    axle_count = db.Column(db.Integer, nullable=True)
    size_label = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    work_orders = db.relationship(
        "WorkOrder",
        back_populates="equipment",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Equipment {self.code} - {self.equipment_type}>"