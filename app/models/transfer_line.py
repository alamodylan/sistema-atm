from datetime import UTC, datetime

from app.extensions import db


class TransferLine(db.Model):
    __tablename__ = "transfer_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    transfer_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.transfers.id"),
        nullable=False,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    quantity_sent = db.Column(db.Numeric(14, 2), nullable=False)
    quantity_received = db.Column(db.Numeric(14, 2), nullable=True)

    line_status = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    transfer = db.relationship(
        "Transfer",
        foreign_keys=[transfer_id],
    )

    article = db.relationship(
        "Article",
        foreign_keys=[article_id],
    )

    def __repr__(self) -> str:
        return (
            f"<TransferLine id={self.id} transfer_id={self.transfer_id} "
            f"article_id={self.article_id} line_status={self.line_status}>"
        )