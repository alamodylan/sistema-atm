from app.extensions import db


class EquipmentType(db.Model):
    __tablename__ = "equipment_types"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    equipment = db.relationship(
        "Equipment",
        back_populates="equipment_type_ref",
        lazy="dynamic",
    )