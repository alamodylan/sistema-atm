from datetime import datetime, UTC

from app.extensions import db


class Toolbox(db.Model):
    __tablename__ = "toolboxes"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    toolbox_number = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        index=True,
    )

    assigned_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
    )

    assigned_at = db.Column(db.DateTime(timezone=True), nullable=True)

    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # RELACIONES

    warehouse = db.relationship(
        "Warehouse",
        back_populates="toolboxes",
    )

    assigned_user = db.relationship(
        "User",
    )

    def __repr__(self) -> str:
        return f"<Toolbox {self.toolbox_number}>"