from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from common.db import Base

class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"), nullable=False)
    pa_request_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.pa_requests.id"))
    type = Column(SAEnum("status_change", "rfi_received", "approval", "denial", "expiring_auth",
                         "peer_review_required", "sla_warning", "system_alert", "new_guideline",
                         name="notification_type", schema="OneClick"), nullable=False)
    title = Column(String(300), nullable=False)
    message = Column(Text, nullable=False)
    action_url = Column(String(500))
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # role = relationship("User") # Decoupled
