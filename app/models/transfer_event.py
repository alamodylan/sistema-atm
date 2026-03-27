from datetime import datetime, UTC

from app.extensions import db


class TransferEvent(db.Model):
    __tablename__ = "transfer_events"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    transfer_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.transfers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type = db.Column(db.String(40), nullable=False, index=True)
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
        back_populates="events",
    )

    performed_by_user = db.relationship(
        "User",
        foreign_keys=[performed_by_user_id],
    )

    def __repr__(self) -> str:
        return f"<TransferEvent id={self.id} transfer={self.transfer_id} type={self.event_type}>"