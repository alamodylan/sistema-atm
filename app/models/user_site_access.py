from datetime import datetime, UTC

from app.extensions import db


class UserSiteAccess(db.Model):
    __tablename__ = "user_site_access"
    __table_args__ = {"schema": "atm"}

    id = db.Column(db.BigInteger, primary_key=True)

    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    site_id = db.Column(
        db.BigInteger,
        db.ForeignKey("atm.sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    user = db.relationship("User")
    site = db.relationship("Site", back_populates="user_access")

    def __repr__(self) -> str:
        return f"<UserSiteAccess user={self.user_id} site={self.site_id}>"