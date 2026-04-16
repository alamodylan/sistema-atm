from datetime import UTC, datetime

from app.extensions import db


class Transfer(db.Model):
    __tablename__ = "transfers"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)
    number = db.Column(db.String(50), nullable=False, unique=True)

    created_from_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.transfer_requests.id"),
        nullable=True,
        index=True,
    )

    created_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
        index=True,
    )

    origin_site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=False,
        index=True,
    )
    origin_warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id"),
        nullable=False,
        index=True,
    )

    destination_site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=False,
        index=True,
    )
    destination_warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id"),
        nullable=False,
        index=True,
    )

    status = db.Column(db.String(30), nullable=False)

    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    received_at = db.Column(db.DateTime(timezone=True), nullable=True)

    received_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
        index=True,
    )

    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    created_from_request = db.relationship(
        "TransferRequest",
        foreign_keys=[created_from_request_id],
    )

    created_by_user = db.relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )
    received_by_user = db.relationship(
        "User",
        foreign_keys=[received_by_user_id],
    )

    origin_site = db.relationship(
        "Site",
        foreign_keys=[origin_site_id],
    )
    destination_site = db.relationship(
        "Site",
        foreign_keys=[destination_site_id],
    )

    origin_warehouse = db.relationship(
        "Warehouse",
        foreign_keys=[origin_warehouse_id],
        back_populates="transfers_as_origin"
    )
    destination_warehouse = db.relationship(
        "Warehouse",
        foreign_keys=[destination_warehouse_id],
        back_populates="transfers_as_destination"
    )

    lines = db.relationship(
        "TransferLine",
        foreign_keys="TransferLine.transfer_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    events = db.relationship(
        "TransferEvent",
        foreign_keys="TransferEvent.transfer_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Transfer id={self.id} number={self.number} status={self.status}>"