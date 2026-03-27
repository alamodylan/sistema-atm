from datetime import datetime, UTC

from app.extensions import db


class WasteAct(db.Model):
    __tablename__ = "waste_acts"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=False,
        index=True,
    )

    warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id"),
        nullable=False,
        index=True,
    )

    date_from = db.Column(db.Date, nullable=False, index=True)
    date_to = db.Column(db.Date, nullable=False, index=True)

    created_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
        index=True,
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="BORRADOR",
        index=True,
    )
    # Valores oficiales:
    # BORRADOR, REGISTRADA, IMPRESA, CERRADA, CANCELADA

    notes = db.Column(db.Text, nullable=True)

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

    site = db.relationship("Site", back_populates="waste_acts")

    warehouse = db.relationship(
        "Warehouse",
        back_populates="waste_acts",
    )

    created_by_user = db.relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )

    lines = db.relationship(
        "WasteActLine",
        back_populates="waste_act",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<WasteAct {self.number} - {self.status}>"