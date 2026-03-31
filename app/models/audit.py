from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.sql import func
import uuid
from app.db.session import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"))
    pa_request_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.pa_requests.id"))
    patient_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patients.id"))
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100))
    resource_id = Column(UUID(as_uuid=True))
    old_value = Column(JSONB)
    new_value = Column(JSONB)
    ip_address = Column(INET)
    user_agent = Column(Text)
    session_id = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
