from app.extensions import db


class Equipment(db.Model):
    __tablename__ = "equipment"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    code = db.Column(db.String, unique=True, nullable=False)

    equipment_type = db.Column(db.String, nullable=False)

    equipment_type_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.equipment_types.id"),
        nullable=True,
    )

    description = db.Column(db.Text)

    axle_count = db.Column(db.Integer)

    size_label = db.Column(db.String)

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        nullable=False,
    )

    equipment_type_ref = db.relationship(
        "EquipmentType",
        back_populates="equipment",
    )

    work_orders = db.relationship(
        "WorkOrder",
        back_populates="equipment",
        lazy="dynamic",
    )

    @property
    def display_name(self):
        if self.equipment_type_ref:
            return f"{self.code} - {self.equipment_type_ref.name}"
        return f"{self.code} - {self.equipment_type}"