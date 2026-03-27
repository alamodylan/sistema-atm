from app.extensions import db


class ItemCategory(db.Model):
    __tablename__ = "item_categories"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)
    code = db.Column(db.String(50), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    articles = db.relationship(
        "Article",
        back_populates="category",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<ItemCategory {self.code} - {self.name}>"