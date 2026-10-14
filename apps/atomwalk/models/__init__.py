"""
Every table of the shared Atomwalk database, grouped by topic:

  patient    patients, who looks after whom, portal bookings
  documents  batches, medical documents, extracted text
  clinical   diagnoses, prescriptions, labs, allergies, vitals, birth history, vaccinations, milestones
  schedules  immunization and milestone schedules
  access     OTP codes, revoked tokens, consult pads, emergency access, sharing, privacy
"""
from .patient import (  # noqa: F401
    Patient,
    PatientRelationship,
    mobile_hash_of,
    PatientAccount,
    PatientBooking,
)
from .documents import (  # noqa: F401
    get_file_path,
    DocumentBatch,
    MedicalDocument,
    DocumentText,
    PatientDocumentClassification,
    records_storage,
)
from .clinical import (  # noqa: F401
    SharedDiagnosis,
    SharedPrescription,
    SharedPrescriptionItem,
    SharedLabResult,
    SharedAllergy,
    SharedVital,
    SharedBirthHistory,
    SharedVaccination,
    MilestoneRecord,
)
from .schedules import (  # noqa: F401
    Schedule,
    ScheduleRule,
    VaccinationSchedule,
    MilestoneSchedule,
    VaccinationScheduleRule,
    MilestoneScheduleRule,
)
from .access import (  # noqa: F401
    StaffMobileIndex,
    BlacklistedToken,
    OTPCode,
    EmergencyAccessLog,
    ConsultSession,
    RecordsShareRequest,
    RecordsPrivacy,
    new_pad_token,
)
