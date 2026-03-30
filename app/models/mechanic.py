from datetime import UTC, datetime

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

    is_active = db.Column(db.Boolean, nullable=False, default=True)

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

    def __repr__(self) -> str:
        return f"<Mechanic site={self.site_id} code={self.code} - {self.name}>"