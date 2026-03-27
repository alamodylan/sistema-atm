from datetime import datetime, UTC

from app.extensions import db


class TransferRequest(db.Model):
    __tablename__ = "transfer_requests"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    requested_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=False,
        index=True,
    )

    origin_site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=True,
        index=True,
    )

    origin_warehouse_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.warehouses.id"),
        nullable=True,
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

    priority = db.Column(db.String(20), nullable=False, default="NORMAL", index=True)
    status = db.Column(db.String(30), nullable=False, default="SOLICITADA", index=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    requested_by_user = db.relationship(
        "User",
        foreign_keys=[requested_by_user_id],
    )

    origin_site = db.relationship(
        "Site",
        foreign_keys=[origin_site_id],
        back_populates="transfer_requests_as_origin",
    )

    destination_site = db.relationship(
        "Site",
        foreign_keys=[destination_site_id],
        back_populates="transfer_requests_as_destination",
    )

    origin_warehouse = db.relationship(
        "Warehouse",
        foreign_keys=[origin_warehouse_id],
        back_populates="transfer_requests_as_origin",
    )

    destination_warehouse = db.relationship(
        "Warehouse",
        foreign_keys=[destination_warehouse_id],
        back_populates="transfer_requests_as_destination",
    )

    lines = db.relationship(
        "TransferRequestLine",
        back_populates="transfer_request",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    transfers = db.relationship(
        "Transfer",
        back_populates="created_from_request",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<TransferRequest {self.number} - {self.status}>"