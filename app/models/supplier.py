from app.extensions import db


class Supplier(db.Model):
    __tablename__ = "suppliers"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)
    code = db.Column(db.String(50), nullable=True, unique=True, index=True)
    commercial_name = db.Column(db.String(200), nullable=False, index=True)
    legal_name = db.Column(db.String(200), nullable=True)
    tax_id = db.Column(db.String(100), nullable=True)
    contact_name = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    address = db.Column(db.Text, nullable=True)
    payment_terms = db.Column(db.String(100), nullable=True)
    currency_code = db.Column(db.String(10), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    def __repr__(self) -> str:
        return f"<Supplier {self.code} - {self.commercial_name}>"