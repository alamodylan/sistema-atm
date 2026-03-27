from datetime import datetime, UTC

from app.extensions import db


class TransferLine(db.Model):
    __tablename__ = "transfer_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    transfer_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.transfers.id", ondelete="CASCADE"),
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
    quantity_received = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    line_status = db.Column(db.String(30), nullable=False, default="PENDIENTE", index=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    transfer = db.relationship(
        "Transfer",
        back_populates="lines",
    )

    article = db.relationship(
        "Article",
        back_populates="transfer_lines",
    )

    def __repr__(self) -> str:
        return (
            f"<TransferLine id={self.id} "
            f"transfer={self.transfer_id} article={self.article_id}>"
        )