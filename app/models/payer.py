from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Numeric, Integer, ARRAY, SmallInteger
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.db.session import Base


class Payer(Base):
    __tablename__ = "payers"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.organizations.id"))
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    type = Column(String(50), nullable=False)
    inquiry_phone = Column(String(20))
    inquiry_fax = Column(String(20))
    portal_url = Column(String(500))
    epa_supported = Column(Boolean, default=False)
    fhir_endpoint = Column(String(500))
    logo_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    plans = relationship("Plan", back_populates="payer")
    policies = relationship("PayerPolicy", back_populates="payer")
    denial_reasons = relationship("PayerDenialReason", back_populates="payer")
    pa_requests = relationship("PaRequest", back_populates="payer")


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payer_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.payers.id"), nullable=False)
    name = Column(String(255), nullable=False)
    plan_type = Column(String(50), nullable=False)
    group_prefix = Column(String(20))
    member_id_prefix = Column(String(20))
    pa_phone = Column(String(20))
    pa_fax = Column(String(20))
    pa_portal_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    payer = relationship("Payer", back_populates="plans")


class PayerPolicy(Base):
    __tablename__ = "payer_policies"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payer_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.payers.id"), nullable=False)
    policy_number = Column(String(100))
    title = Column(String(300), nullable=False)
    service_category = Column(String(100))
    cpt_codes = Column(ARRAY(String))
    hcpcs_codes = Column(ARRAY(String))
    icd10_codes = Column(ARRAY(String))
    requirements = Column(JSONB, default=[])
    medical_necessity_criteria = Column(JSONB, default=[])
    step_therapy_required = Column(Boolean, default=False)
    prior_auth_required = Column(Boolean, default=True)
    clinical_guidelines = Column(Text)
    approval_criteria = Column(Text)
    denial_criteria = Column(Text)
    effective_date = Column(DateTime)
    review_date = Column(DateTime)
    version = Column(String(20))
    source_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    payer = relationship("Payer", back_populates="policies")


class PayerDenialReason(Base):
    __tablename__ = "payer_denial_reasons"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payer_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.payers.id"), nullable=False)
    cpt_code = Column(String(10))
    reason_code = Column(String(50))
    reason_description = Column(String(500), nullable=False)
    frequency_percent = Column(Numeric(5, 2))
    period_days = Column(Integer, default=90)
    impact_level = Column(String(20))
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    payer = relationship("Payer", back_populates="denial_reasons")


class PaCoverageRule(Base):
    __tablename__ = "payer_coverage_rules"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payer_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.payers.id"), nullable=False)
    plan_type = Column(String(50))
    cpt_code = Column(String(10))
    hcpcs_code = Column(String(10))
    requires_pa = Column(Boolean, default=True)
    pa_validity_days = Column(Integer, default=180)
    max_units = Column(Integer)
    quantity_limit = Column(Integer)
    age_min = Column(SmallInteger)
    age_max = Column(SmallInteger)
    gender_restriction = Column(String(10))
    notes = Column(Text)
    effective_date = Column(DateTime)
    termination_date = Column(DateTime)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
