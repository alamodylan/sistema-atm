from datetime import datetime, UTC

from app.extensions import db


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    recipient_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    notification_type = db.Column(db.String(40), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)

    entity_type = db.Column(db.String(50), nullable=True)
    entity_id = db.Column(db.BigInteger, nullable=True)

    is_read = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    read_at = db.Column(db.DateTime(timezone=True), nullable=True)

    recipient_user = db.relationship(
        "User",
        foreign_keys=[recipient_user_id],
    )

    def __repr__(self) -> str:
        return f"<Notification user={self.recipient_user_id} type={self.notification_type}>"