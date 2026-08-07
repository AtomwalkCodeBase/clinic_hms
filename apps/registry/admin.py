from django.contrib import admin
from .models import (
    PatientIdentity,
    SharedDiagnosis,
    SharedPrescription,
    SharedLabResult,
    SharedAllergy,
    SharedVital,
)


@admin.register(PatientIdentity)
class PatientIdentityAdmin(admin.ModelAdmin):
    list_display    = ["awpid", "full_name", "date_of_birth", "gender", "created_at"]
    search_fields   = ["awpid", "full_name", "email"]
    readonly_fields = ["awpid", "mobile_hash", "created_at", "updated_at"]


@admin.register(SharedDiagnosis)
class SharedDiagnosisAdmin(admin.ModelAdmin):
    list_display  = ["awpid", "icd10_code", "clinical_status", "created_at"]
    search_fields = ["awpid", "icd10_code"]


@admin.register(SharedLabResult)
class SharedLabResultAdmin(admin.ModelAdmin):
    list_display  = ["awpid", "test_name", "delivered_at"]
    search_fields = ["awpid", "test_name"]


admin.site.register(SharedPrescription)
admin.site.register(SharedAllergy)
admin.site.register(SharedVital)
