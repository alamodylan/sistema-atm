from app.extensions import db


class ServiceCatalog(db.Model):
    __tablename__ = "services_catalog"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    category = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    work_order_services = db.relationship(
        "WorkOrderService",
        back_populates="service",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<ServiceCatalog {self.code} - {self.name}>"