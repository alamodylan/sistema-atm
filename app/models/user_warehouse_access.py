from datetime import datetime, UTC

from app.extensions import db


class UserWarehouseAccess(db.Model):
    __tablename__ = "user_warehouse_access"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    user = db.relationship("User")
    warehouse = db.relationship("Warehouse")

    def __repr__(self) -> str:
        return f"<UserWarehouseAccess user={self.user_id} wh={self.warehouse_id}>"