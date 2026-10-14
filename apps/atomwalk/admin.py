from django.contrib import admin
from .models import (
    Patient,
    ClinicalEvent,
    LabResult,
    SharedAllergy,
    Vitals,
    GrowthMeasurement,
    VaccinationSchedule,
    VaccinationScheduleRule,
)


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display    = ["awpid", "full_name", "date_of_birth", "gender", "created_at"]
    search_fields   = ["awpid", "full_name", "email"]
    readonly_fields = ["awpid", "mobile_hash", "created_at", "updated_at"]


@admin.register(ClinicalEvent)
class ClinicalEventAdmin(admin.ModelAdmin):
    list_display  = ["patient", "event_type", "icd10", "clinical_status", "event_date"]
    search_fields = ["patient__awpid", "icd10"]


@admin.register(LabResult)
class LabResultAdmin(admin.ModelAdmin):
    list_display  = ["patient", "test_name", "delivered_at"]
    search_fields = ["patient__awpid", "test_name"]


admin.site.register(SharedAllergy)
admin.site.register(Vitals)
admin.site.register(GrowthMeasurement)


class VaccinationScheduleRuleInline(admin.TabularInline):
    model = VaccinationScheduleRule
    extra = 1


@admin.register(VaccinationSchedule)
class VaccinationScheduleAdmin(admin.ModelAdmin):
    list_display  = ["name", "owner_hospital_id", "is_template", "active", "updated_at"]
    search_fields = ["name"]
    list_filter   = ["is_template", "active"]
    inlines       = [VaccinationScheduleRuleInline]
