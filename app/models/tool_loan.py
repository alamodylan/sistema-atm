from datetime import datetime, UTC

from app.extensions import db


class ToolLoan(db.Model):
    __tablename__ = "tool_loans"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    work_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    request_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_order_request_lines.id"),
        nullable=True,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id"),
        nullable=False,
        index=True,
    )

    requested_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
        index=True,
    )

    delivered_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
    )

    returned_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
    )

    received_return_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
    )

    quantity = db.Column(db.Numeric(14, 2), nullable=False, default=1)

    loan_status = db.Column(
        db.String(20),
        nullable=False,
        default="PRESTADA",
        index=True,
    )

    notes = db.Column(db.Text, nullable=True)

    loaned_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    returned_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # RELACIONES

    work_order = db.relationship(
        "WorkOrder",
        back_populates="tool_loans",
    )

    request_line = db.relationship(
        "WorkOrderRequestLine",
    )

    article = db.relationship(
        "Article",
        back_populates="tool_loans",
    )

    warehouse = db.relationship(
        "Warehouse",
        back_populates="tool_loans",
    )

    requested_by_user = db.relationship(
        "User",
        foreign_keys=[requested_by_user_id],
    )

    delivered_by_user = db.relationship(
        "User",
        foreign_keys=[delivered_by_user_id],
    )

    returned_by_user = db.relationship(
        "User",
        foreign_keys=[returned_by_user_id],
    )

    received_return_by_user = db.relationship(
        "User",
        foreign_keys=[received_return_by_user_id],
    )

    def __repr__(self) -> str:
        return f"<ToolLoan id={self.id} article={self.article_id} status={self.loan_status}>"