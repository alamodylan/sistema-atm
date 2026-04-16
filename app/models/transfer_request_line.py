from datetime import UTC, datetime

from app.extensions import db


class TransferRequestLine(db.Model):
    __tablename__ = "transfer_request_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    transfer_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.transfer_requests.id"),
        nullable=False,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    quantity_requested = db.Column(db.Numeric(14, 2), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    transfer_request = db.relationship(
        "TransferRequest",
        foreign_keys=[transfer_request_id],
    )

    article = db.relationship(
        "Article",
        foreign_keys=[article_id],
    )

    def __repr__(self) -> str:
        return (
            f"<TransferRequestLine id={self.id} "
            f"transfer_request_id={self.transfer_request_id} article_id={self.article_id}>"
        )