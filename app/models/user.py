from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.db.session import Base


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    npi = Column(String(20), unique=True)
    tax_id = Column(String(20))
    address_line1 = Column(String(255))
    address_line2 = Column(String(100))
    city = Column(String(100))
    state = Column(String(2))
    zip = Column(String(10))
    phone = Column(String(20))
    fax = Column(String(20))
    website = Column(String(255))
    logo_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    users = relationship("User", back_populates="organization")
    patients = relationship("Patient", back_populates="organization")


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.organizations.id"))
    role = Column(SAEnum("provider", "payer_intake", "payer_clinical", "payer_decision", "admin", "super_admin",
                         name="user_role", schema="OneClick"), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    title = Column(String(50))
    specialty = Column(String(100))
    npi = Column(String(20))
    license_number = Column(String(50))
    phone = Column(String(20))
    profile_picture = Column(String(500))
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    organization = relationship("Organization", back_populates="users")
    pa_requests = relationship("PaRequest", foreign_keys="PaRequest.requesting_provider_id", back_populates="requesting_provider")
    notifications = relationship("Notification", back_populates="user")

    @property
    def full_name(self):
        title = f"{self.title} " if self.title else ""
        return f"{title}{self.first_name} {self.last_name}"
