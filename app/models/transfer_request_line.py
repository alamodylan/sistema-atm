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

    quantity_approved = db.Column(db.Numeric(14, 2), nullable=True)
    quantity_attended = db.Column(db.Numeric(14, 2), nullable=True)

    manager_review_status = db.Column(db.String(20), nullable=True)

    manager_reviewed_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    manager_reviewed_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True,
    )

    line_status = db.Column(db.String(30), nullable=True)
    not_delivered_reason = db.Column(db.Text, nullable=True)

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

    manager_reviewed_by_user = db.relationship(
        "User",
        foreign_keys=[manager_reviewed_by_user_id],
    )

    def __repr__(self) -> str:
        return (
            f"<TransferRequestLine id={self.id} "
            f"transfer_request_id={self.transfer_request_id} article_id={self.article_id}>"
        )