from datetime import datetime, UTC

from app.extensions import db


class WasteActLine(db.Model):
    __tablename__ = "waste_act_lines"
    __table_args__ = (
        db.UniqueConstraint("work_order_line_id", name="waste_act_lines_work_order_line_id_key"),
        {"schema": "atm"},
    )

    id = db.Column(db.BigInteger, primary_key=True)

    waste_act_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.waste_acts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    work_order_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_orders.id"),
        nullable=False,
        index=True,
    )

    work_order_line_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.work_order_lines.id"),
        nullable=False,
        index=True,
    )

    article_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.articles.id"),
        nullable=False,
        index=True,
    )

    quantity = db.Column(db.Numeric(14, 2), nullable=False)

    confirmed_for_disposal = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    waste_act = db.relationship(
        "WasteAct",
        back_populates="lines",
    )

    work_order = db.relationship(
        "WorkOrder",
        back_populates="waste_act_lines",
    )

    work_order_line = db.relationship(
        "WorkOrderLine",
        back_populates="waste_act_lines",
    )

    article = db.relationship(
        "Article",
        back_populates="waste_act_lines",
    )

    def __repr__(self) -> str:
        return (
            f"<WasteActLine act={self.waste_act_id} "
            f"wo_line={self.work_order_line_id} article={self.article_id}>"
        )