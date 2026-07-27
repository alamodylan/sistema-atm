from datetime import UTC, datetime

from app.extensions import db


class PurchaseOrderCandidate(db.Model):
    __tablename__ = "purchase_order_candidates"
    __table_args__ = (
        db.UniqueConstraint(
            "purchase_request_line_id",
            name="uq_purchase_order_candidates_request_line",
        ),
        db.UniqueConstraint(
            "quotation_line_id",
            name="uq_purchase_order_candidates_quotation_line",
        ),
        db.CheckConstraint(
            "status IN ('PENDING', 'USED', 'CANCELLED')",
            name="ck_purchase_order_candidates_status",
        ),
        {"schema": "atm"},
    )

    id = db.Column(
        db.BigInteger,
        primary_key=True,
    )

    purchase_request_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "atm.purchase_request_lines.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    quotation_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "atm.quotation_lines.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    supplier_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "atm.suppliers.id",
        ),
        nullable=False,
        index=True,
    )

    selected_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "atm.users.id",
        ),
        nullable=False,
    )

    purchase_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "atm.purchase_orders.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="PENDING",
        index=True,
    )

    selected_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    purchase_request_line = db.relationship(
        "PurchaseRequestLine",
        back_populates="purchase_order_candidate",
    )

    quotation_line = db.relationship(
        "QuotationLine",
        back_populates="purchase_order_candidate",
    )

    supplier = db.relationship(
        "Supplier",
    )

    selected_by_user = db.relationship(
        "User",
    )

    purchase_order = db.relationship(
        "PurchaseOrder",
    )