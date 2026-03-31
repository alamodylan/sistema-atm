from app.extensions import db


class PurchaseOrderApproval(db.Model):
    __tablename__ = "purchase_order_approvals"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    purchase_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )

    approved_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
    )

    status = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    purchase_order = db.relationship(
        "PurchaseOrder",
        back_populates="approvals",
    )

    approved_by_user = db.relationship("User")