from app.extensions import db


class WorkOrderRequestLine(db.Model):
    __tablename__ = "work_order_request_lines"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    work_order_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_order_requests.id", ondelete="CASCADE"),
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
    quantity_attended = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    line_status = db.Column(
        db.String(30),
        nullable=False,
        default="SOLICITADA",
        index=True,
    )
    # Valores oficiales:
    # SOLICITADA, ATENDIDA_PARCIAL, ENTREGADA, NO_ENTREGADA, CANCELADA, PRESTADA

    manager_review_status = db.Column(
        db.String(20),
        nullable=False,
        default="PENDIENTE",
        index=True,
    )
    # Valores propuestos:
    # PENDIENTE, APROBADA, RECHAZADA

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

    not_delivered_reason = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    work_order_request = db.relationship(
        "WorkOrderRequest",
        back_populates="lines",
    )

    article = db.relationship(
        "Article",
        back_populates="work_order_request_lines",
    )

    manager_reviewed_by_user = db.relationship(
        "User",
        foreign_keys=[manager_reviewed_by_user_id],
    )

    delivered_lines = db.relationship(
        "WorkOrderLine",
        back_populates="request_line",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkOrderRequestLine id={self.id} "
            f"article={self.article_id} requested={self.quantity_requested}>"
        )