from datetime import datetime, UTC

from app.extensions import db


class RequestRoutingRule(db.Model):
    __tablename__ = "request_routing_rules"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    origin_site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=False,
        index=True,
    )

    request_type = db.Column(
        db.String(50),
        nullable=False,
    )

    routing_mode = db.Column(
        db.String(50),
        nullable=False,
    )

    target_site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id"),
        nullable=True,
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
    )

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

    # =========================================================
    # RELACIONES
    # =========================================================

    origin_site = db.relationship(
        "Site",
        foreign_keys=[origin_site_id],
        lazy="joined",
    )

    target_site = db.relationship(
        "Site",
        foreign_keys=[target_site_id],
        lazy="joined",
    )

    created_by_user = db.relationship(
        "User",
        foreign_keys=[created_by_user_id],
        lazy="joined",
    )

    # =========================================================
    # CONSTANTES
    # =========================================================

    REQUEST_TYPES = [
        "WORK_ORDER_REQUEST",
        "PURCHASE_REQUEST",
        "TRANSFER_REQUEST",
        "TOOL_LOAN_REQUEST",
        "TASK_FINISH_REQUEST",
    ]

    ROUTING_MODES = [
        "LOCAL_MANAGER_DASHBOARD",
        "OTHER_SITE_MANAGER_DASHBOARD",
        "DIRECT_TO_WAREHOUSE",
        "DIRECT_TO_PROCUREMENT",
    ]

    # =========================================================
    # HELPERS
    # =========================================================

    @property
    def requires_target_site(self):
        return self.routing_mode == "OTHER_SITE_MANAGER_DASHBOARD"

    @property
    def is_direct_to_warehouse(self):
        return self.routing_mode == "DIRECT_TO_WAREHOUSE"

    @property
    def is_direct_to_procurement(self):
        return self.routing_mode == "DIRECT_TO_PROCUREMENT"

    @property
    def is_manager_dashboard(self):
        return self.routing_mode in [
            "LOCAL_MANAGER_DASHBOARD",
            "OTHER_SITE_MANAGER_DASHBOARD",
        ]

    def __repr__(self):
        return (
            f"<RequestRoutingRule "
            f"site={self.origin_site_id} "
            f"type={self.request_type} "
            f"mode={self.routing_mode}>"
        )