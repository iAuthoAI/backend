from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Date, Numeric, Text, SmallInteger, Integer, Enum as SAEnum, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.db.session import Base


class PaRequest(Base):
    __tablename__ = "pa_requests"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_number = Column(String(50), unique=True, nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patients.id"), nullable=False)
    coverage_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patient_coverage.id"), nullable=False)
    payer_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.payers.id"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.plans.id"))
    requesting_provider_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"), nullable=False)
    servicing_provider_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"))
    organization_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.organizations.id"), nullable=False)

    cpt_code = Column(String(10), nullable=False)
    cpt_description = Column(String(500))
    hcpcs_code = Column(String(10))
    icd10_primary = Column(String(10), nullable=False)
    icd10_primary_desc = Column(String(500))
    icd10_secondary = Column(ARRAY(String))
    service_description = Column(String(500))
    service_date = Column(Date)
    service_facility = Column(String(255))

    status = Column(
        SAEnum("draft", "submitted", "intake_review", "clinical_review", "decision_pending",
               "approved", "denied", "partial_approval", "action_required", "withdrawn",
               "appeal_submitted", "appeal_approved", "appeal_denied", "expired",
               name="pa_status", schema="OneClick"),
        nullable=False, default="draft"
    )
    priority = Column(
        SAEnum("routine", "urgent", "emergent", "stat", name="request_priority", schema="OneClick"),
        nullable=False, default="routine"
    )
    submission_method = Column(
        SAEnum("epa", "fax", "portal", "phone", "mail", name="submission_method", schema="OneClick")
    )
    pa_form_template_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.pa_form_templates.id"))
    form_data = Column(JSONB, default={})

    clinical_notes = Column(Text)
    clinical_justification = Column(Text)
    failed_conservative_therapy = Column(Boolean)
    conservative_therapy_details = Column(Text)
    neurological_deficits = Column(Boolean)
    neurological_details = Column(Text)

    payer_reference_number = Column(String(100))
    fhir_service_request_id = Column(String(200))

    ai_score = Column(SmallInteger)
    ai_confidence = Column(Numeric(5, 2))
    ai_analysis = Column(JSONB, default={})
    ai_gaps = Column(JSONB, default=[])
    ai_suggestions = Column(JSONB, default=[])

    submitted_at = Column(DateTime(timezone=True))
    intake_started_at = Column(DateTime(timezone=True))
    clinical_started_at = Column(DateTime(timezone=True))
    decision_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))

    decision = Column(String(50))
    decision_reason = Column(Text)
    decision_letter_url = Column(String(500))
    approved_units = Column(Integer)
    approved_from = Column(Date)
    approved_through = Column(Date)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient = relationship("Patient", back_populates="pa_requests")
    payer = relationship("Payer", back_populates="pa_requests")
    requesting_provider = relationship("User", foreign_keys=[requesting_provider_id], back_populates="pa_requests")
    status_history = relationship("PaStatusHistory", back_populates="pa_request")
    documents = relationship("SupportingDocument", back_populates="pa_request")
    coverage = relationship("PatientCoverage")
    form_template = relationship("PaFormTemplate")


class PaStatusHistory(Base):
    __tablename__ = "pa_status_history"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pa_request_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.pa_requests.id"), nullable=False)
    from_status = Column(SAEnum("draft", "submitted", "intake_review", "clinical_review", "decision_pending",
                                "approved", "denied", "partial_approval", "action_required", "withdrawn",
                                "appeal_submitted", "appeal_approved", "appeal_denied", "expired",
                                name="pa_status", schema="OneClick"))
    to_status = Column(SAEnum("draft", "submitted", "intake_review", "clinical_review", "decision_pending",
                              "approved", "denied", "partial_approval", "action_required", "withdrawn",
                              "appeal_submitted", "appeal_approved", "appeal_denied", "expired",
                              name="pa_status", schema="OneClick"), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"))
    changed_by_role = Column(SAEnum("provider", "payer_intake", "payer_clinical", "payer_decision", "admin", "super_admin",
                                    name="user_role", schema="OneClick"))
    notes = Column(Text)
    ai_triggered = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    pa_request = relationship("PaRequest", back_populates="status_history")


class SupportingDocument(Base):
    __tablename__ = "supporting_documents"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pa_request_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.pa_requests.id"), nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"))
    document_type = Column(SAEnum("clinical_note", "lab_result", "imaging_report", "referral", "prior_auth_form",
                                  "appeal_letter", "eob", "prescription", "other",
                                  name="document_type", schema="OneClick"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer)
    mime_type = Column(String(100))
    storage_key = Column(String(500))
    storage_url = Column(String(1000))
    description = Column(Text)
    extracted_text = Column(Text)
    ai_summary = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    pa_request = relationship("PaRequest", back_populates="documents")


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patients.id"), nullable=False)
    pa_request_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.pa_requests.id"))
    author_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"), nullable=False)
    note_type = Column(String(50), nullable=False)
    title = Column(String(300))
    content = Column(Text, nullable=False)
    is_signed = Column(Boolean, default=False)
    signed_at = Column(DateTime(timezone=True))
    fhir_note_id = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient = relationship("Patient", back_populates="clinical_notes")
    author = relationship("User")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patients.id"), nullable=False)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.organizations.id"), nullable=False)
    appointment_type = Column(String(50))
    scheduled_time = Column(DateTime(timezone=True), nullable=False)
    room = Column(String(50))
    chief_complaint = Column(String(300))
    status = Column(String(30), default="scheduled")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="appointments")
    provider = relationship("User")
