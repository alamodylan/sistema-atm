from datetime import datetime, UTC

from app.extensions import db


class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    role_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    permission_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    role = db.relationship(
        "Role",
        back_populates="role_permissions",
    )

    permission = db.relationship(
        "Permission",
        back_populates="role_permissions",
    )

    def __repr__(self):
        return f"<RolePermission role={self.role_id} perm={self.permission_id}>"