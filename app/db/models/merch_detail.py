from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class MerchDetail(Base):

    __tablename__ = "merch_details"

    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)
    idol_id = Column(UUID(as_uuid=True), ForeignKey("idols.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True, index=True)
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True, index=True)
    edition = Column(String, nullable=True)  # e.g. "Ver. 3", "10th Anniversary Edition" — free text, not worth a lookup table
    color_id = Column(UUID(as_uuid=True), ForeignKey("idol_colors.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True)  # reuses idol_colors (§2)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # Strict XOR, unlike album_details' "at least one of": a merch detail is
        # always either an idol's personal design or a group's official one.
        CheckConstraint(
            "(idol_id IS NOT NULL AND group_id IS NULL) OR (idol_id IS NULL AND group_id IS NOT NULL)",
            name="chk_merch_details_owner",
        ),
    )

    product = relationship("Product")
    idol = relationship("Idol")
    group = relationship("Group")
    color = relationship("IdolColor")
