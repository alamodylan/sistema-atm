from datetime import datetime, UTC

from app.extensions import db


class ItemSubcategory(db.Model):
    __tablename__ = "item_subcategories"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    category_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.item_categories.id"),
        nullable=False,
        index=True,
    )

    code = db.Column(db.String(50), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    category = db.relationship(
        "ItemCategory",
        back_populates="subcategories",
    )

    articles = db.relationship(
        "Article",
        back_populates="subcategory",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<ItemSubcategory {self.name}>"