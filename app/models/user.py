from datetime import datetime, UTC

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=True, index=True)

    password_hash = db.Column(db.String(255), nullable=False)

    role_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.roles.id"),
        nullable=False,
        index=True,
    )

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_shared_account = db.Column(db.Boolean, nullable=False, default=False)

    barcode_value = db.Column(db.String(100), unique=True, nullable=True, index=True)

    created_by_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id"),
        nullable=True,
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

    role = db.relationship("Role", back_populates="users")

    created_by_user = db.relationship(
        "User",
        remote_side=[id],
        foreign_keys=[created_by_user_id],
        back_populates="created_users",
    )

    created_users = db.relationship(
        "User",
        back_populates="created_by_user",
        foreign_keys=[created_by_user_id],
        lazy="dynamic",
    )

    audit_logs = db.relationship("AuditLog", back_populates="user", lazy="dynamic")

    responsible_work_orders = db.relationship(
        "WorkOrder",
        foreign_keys="WorkOrder.responsible_user_id",
        back_populates="responsible_user",
        lazy="dynamic",
    )

    created_work_orders = db.relationship(
        "WorkOrder",
        foreign_keys="WorkOrder.created_by_user_id",
        back_populates="created_by_user",
        lazy="dynamic",
    )

    delivered_work_order_lines = db.relationship(
        "WorkOrderLine",
        foreign_keys="WorkOrderLine.delivered_by_user_id",
        back_populates="delivered_by_user",
        lazy="dynamic",
    )

    received_work_order_lines = db.relationship(
        "WorkOrderLine",
        foreign_keys="WorkOrderLine.received_by_user_id",
        back_populates="received_by_user",
        lazy="dynamic",
    )

    requested_delete_requests = db.relationship(
        "WorkOrderLineDeleteRequest",
        foreign_keys="WorkOrderLineDeleteRequest.requested_by_user_id",
        back_populates="requested_by_user",
        lazy="dynamic",
    )

    reviewed_delete_requests = db.relationship(
        "WorkOrderLineDeleteRequest",
        foreign_keys="WorkOrderLineDeleteRequest.reviewed_by_user_id",
        back_populates="reviewed_by_user",
        lazy="dynamic",
    )

    work_order_requests = db.relationship(
        "WorkOrderRequest",
        foreign_keys="WorkOrderRequest.requested_by_user_id",
        back_populates="requested_by_user",
        lazy="dynamic",
    )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    def get_id(self) -> str:
        return str(self.id)

    def __repr__(self) -> str:
        return f"<User {self.username}>"