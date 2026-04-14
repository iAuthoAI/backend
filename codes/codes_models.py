from sqlalchemy import Column, String, Boolean, DateTime, Numeric, SmallInteger, ARRAY, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from common.db import Base

class CptCode(Base):
    __tablename__ = "cpt_codes"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(10), unique=True, nullable=False)
    description = Column(String(500), nullable=False)
    short_description = Column(String(200))
    category = Column(String(100))
    subcategory = Column(String(100))
    specialty = Column(String(100))
    typical_pa_required = Column(Boolean, default=False)
    rvu = Column(Numeric(8, 2))
    global_period = Column(SmallInteger)
    is_active = Column(Boolean, default=True)
    effective_date = Column(Date)
    termination_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class HcpcsCode(Base):
    __tablename__ = "hcpcs_codes"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(10), unique=True, nullable=False)
    description = Column(String(500), nullable=False)
    short_description = Column(String(200))
    category = Column(String(100))
    level = Column(SmallInteger)
    typical_pa_required = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    effective_date = Column(Date)
    termination_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Icd10Code(Base):
    __tablename__ = "icd10_codes"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(10), unique=True, nullable=False)
    description = Column(String(500), nullable=False)
    short_description = Column(String(200))
    chapter = Column(String(100))
    category = Column(String(100))
    billable = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    effective_date = Column(Date)
    termination_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
