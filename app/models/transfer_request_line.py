from datetime import datetime, UTC

from app.extensions import db


class TransferRequestLine(db.Model):
    __tablename__ = "transfer_request_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    transfer_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.transfer_requests.id", ondelete="CASCADE"),
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
        back_populates="lines",
    )

    article = db.relationship(
        "Article",
        back_populates="transfer_request_lines",
    )

    def __repr__(self) -> str:
        return (
            f"<TransferRequestLine id={self.id} "
            f"request={self.transfer_request_id} article={self.article_id}>"
        )