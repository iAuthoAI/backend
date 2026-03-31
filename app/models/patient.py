from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Date, Numeric, Text, SmallInteger, Integer, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.db.session import Base


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.organizations.id"))
    mrn = Column(String(50), unique=True, nullable=False)
    fhir_patient_id = Column(String(100))
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    middle_name = Column(String(100))
    date_of_birth = Column(Date, nullable=False)
    gender = Column(SAEnum("male", "female", "other", "unknown", name="gender", schema="OneClick"), nullable=False)
    ssn_last4 = Column(String(4))
    phone = Column(String(20))
    email = Column(String(255))
    address_line1 = Column(String(255))
    address_line2 = Column(String(100))
    city = Column(String(100))
    state = Column(String(2))
    zip = Column(String(10))
    emergency_contact_name = Column(String(200))
    emergency_contact_phone = Column(String(20))
    emergency_contact_relation = Column(String(50))
    allergies = Column(JSONB, default=[])
    code_status = Column(String(50), default="Full Code")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    organization = relationship("Organization", back_populates="patients")
    coverage = relationship("PatientCoverage", back_populates="patient")
    problems = relationship("PatientProblem", back_populates="patient")
    medications = relationship("PatientMedication", back_populates="patient")
    labs = relationship("PatientLab", back_populates="patient")
    vitals = relationship("PatientVital", back_populates="patient")
    appointments = relationship("Appointment", back_populates="patient")
    pa_requests = relationship("PaRequest", back_populates="patient")
    clinical_notes = relationship("ClinicalNote", back_populates="patient")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class PatientCoverage(Base):
    __tablename__ = "patient_coverage"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patients.id"), nullable=False)
    payer_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.payers.id"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.plans.id"))
    coverage_order = Column(SmallInteger, nullable=False)
    member_id = Column(String(100), nullable=False)
    group_number = Column(String(100))
    subscriber_name = Column(String(200))
    subscriber_dob = Column(Date)
    subscriber_relationship = Column(String(50))
    copay = Column(Numeric(10, 2))
    deductible = Column(Numeric(10, 2))
    out_of_pocket_max = Column(Numeric(10, 2))
    effective_date = Column(Date)
    termination_date = Column(Date)
    is_active = Column(Boolean, default=True)
    is_selected_for_pa = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient = relationship("Patient", back_populates="coverage")
    payer = relationship("Payer")
    plan = relationship("Plan")


class PatientProblem(Base):
    __tablename__ = "patient_problems"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patients.id"), nullable=False)
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"))
    icd10_code = Column(String(10))
    problem_name = Column(String(300), nullable=False)
    onset_date = Column(Date)
    resolution_date = Column(Date)
    status = Column(String(30), default="active")
    notes = Column(Text)
    fhir_condition_id = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="problems")


class PatientMedication(Base):
    __tablename__ = "patient_medications"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patients.id"), nullable=False)
    prescribed_by = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"))
    medication_name = Column(String(255), nullable=False)
    generic_name = Column(String(255))
    dose = Column(String(100))
    route = Column(String(50))
    frequency = Column(String(100))
    start_date = Column(Date)
    end_date = Column(Date)
    is_active = Column(Boolean, default=True)
    rx_norm_code = Column(String(50))
    ndc_code = Column(String(50))
    fhir_medication_id = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="medications")


class PatientLab(Base):
    __tablename__ = "patient_labs"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patients.id"), nullable=False)
    pa_request_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.pa_requests.id"))
    ordered_by = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"))
    test_name = Column(String(255), nullable=False)
    loinc_code = Column(String(20))
    result_value = Column(String(100))
    result_unit = Column(String(50))
    reference_range = Column(String(100))
    is_abnormal = Column(Boolean, default=False)
    abnormal_flag = Column(String(10))
    specimen_type = Column(String(50))
    collected_at = Column(DateTime(timezone=True))
    resulted_at = Column(DateTime(timezone=True))
    fhir_observation_id = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="labs")


class PatientVital(Base):
    __tablename__ = "patient_vitals"
    __table_args__ = {"schema": "OneClick"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.patients.id"), nullable=False)
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("OneClick.users.id"))
    appointment_id = Column(UUID(as_uuid=True), ForeignKey("OneClick.appointments.id"))
    bp_systolic = Column(SmallInteger)
    bp_diastolic = Column(SmallInteger)
    heart_rate = Column(SmallInteger)
    temperature = Column(Numeric(5, 2))
    respiratory_rate = Column(SmallInteger)
    spo2 = Column(SmallInteger)
    weight_kg = Column(Numeric(6, 2))
    height_cm = Column(Numeric(5, 2))
    bmi = Column(Numeric(5, 2))
    pain_score = Column(SmallInteger)
    fhir_observation_id = Column(String(200))
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="vitals")
