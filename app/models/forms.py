from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Date, ARRAY, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.db.session import Base


class PaFormTemplate(Base):
    __tablename__ = "pa_form_templates"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payer_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.payers.id"))
    form_id = Column(String(100), unique=True, nullable=False)
    title = Column(String(300), nullable=False)
    description = Column(String(500))
    form_type = Column(SAEnum("imaging", "pharmacy", "medical_injectables", "general", "specialty_pharmacy",
                              name="form_type", schema="OneClick"), nullable=False)
    version = Column(String(20))
    revision_date = Column(Date)
    cpt_codes = Column(ARRAY(String))
    hcpcs_codes = Column(ARRAY(String))
    drug_categories = Column(ARRAY(String))
    fields = Column(JSONB, nullable=False, default=[])
    is_epa = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    payer = relationship("Payer")
