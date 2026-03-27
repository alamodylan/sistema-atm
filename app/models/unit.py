from app.extensions import db


class Unit(db.Model):
    __tablename__ = "units"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)
    code = db.Column(db.String(20), nullable=False, unique=True, index=True)
    name = db.Column(db.String(50), nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    articles = db.relationship(
        "Article",
        back_populates="unit",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Unit {self.code} - {self.name}>"