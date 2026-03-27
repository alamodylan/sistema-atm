from datetime import datetime, UTC

from app.extensions import db


class Role(db.Model):
    __tablename__ = "roles"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    users = db.relationship("User", back_populates="role", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Role {self.code} - {self.name}>"