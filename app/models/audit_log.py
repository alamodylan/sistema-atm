from datetime import datetime, UTC

from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    action = db.Column(db.String(50), nullable=False, index=True)
    table_name = db.Column(db.String(100), nullable=False, index=True)
    record_id = db.Column(db.String(100), nullable=False, index=True)

    details = db.Column(db.JSON, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    user = db.relationship("User", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.table_name}:{self.record_id}>"