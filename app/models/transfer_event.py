from datetime import UTC, datetime

from app.extensions import db


class TransferEvent(db.Model):
    __tablename__ = "transfer_events"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    transfer_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.transfers.id"),
        nullable=False,
        index=True,
    )

    event_type = db.Column(db.String(50), nullable=False)
    event_message = db.Column(db.Text, nullable=True)

    performed_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    transfer = db.relationship(
        "Transfer",
        foreign_keys=[transfer_id],
    )

    performed_by_user = db.relationship(
        "User",
        foreign_keys=[performed_by_user_id],
    )

    def __repr__(self) -> str:
        return f"<TransferEvent id={self.id} transfer_id={self.transfer_id} event_type={self.event_type}>"