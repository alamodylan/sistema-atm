from datetime import datetime, UTC
from app.extensions import db


class TransferDocument(db.Model):
    __tablename__ = "transfer_documents"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    transfer_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.transfers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    document_type = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    file_data = db.Column(db.LargeBinary, nullable=False)

    generated_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
    )

    generated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    transfer = db.relationship("Transfer")
    generated_by_user = db.relationship("User")