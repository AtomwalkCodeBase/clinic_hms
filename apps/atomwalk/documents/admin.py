from django.contrib import admin

from apps.atomwalk.documents.models import ClinicalEvent, GrowthMeasurement, LabResult, SharedAllergy, Vitals, VaccinationSchedule, VaccinationScheduleRule

from apps.atomwalk.documents.models import DocumentBatch, DocumentExtraction, MedicalDocument, PatientDocumentClassification


@admin.register(DocumentBatch)
class DocumentBatchAdmin(admin.ModelAdmin):
    list_display = ["id", "patient", "total_files", "processed_files", "failed_files", "status", "created_at"]
    search_fields = ["patient__awpid"]


class DocumentExtractionInline(admin.StackedInline):
    model = DocumentExtraction
    extra = 0
    readonly_fields = ["extracted_text", "engine", "normalised", "created_at"]
    can_delete = False


class PatientDocumentClassificationInline(admin.StackedInline):
    model = PatientDocumentClassification
    extra = 0
    can_delete = False


@admin.register(MedicalDocument)
class MedicalDocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "patient", "file_name", "document_type", "status", "created_at"]
    list_filter = ["status", "document_type", "uploaded_by"]
    search_fields = ["patient__awpid", "file_name"]
    readonly_fields = ["error_message", "created_at", "updated_at"]
    inlines = [DocumentExtractionInline, PatientDocumentClassificationInline]


@admin.register(ClinicalEvent)
class ClinicalEventAdmin(admin.ModelAdmin):
    list_display = ["patient", "event_type", "icd10", "clinical_status", "event_date"]
    search_fields = ["patient__awpid", "icd10"]


@admin.register(LabResult)
class LabResultAdmin(admin.ModelAdmin):
    list_display = ["patient", "test_name", "delivered_at"]
    search_fields = ["patient__awpid", "test_name"]


admin.site.register(SharedAllergy)
admin.site.register(Vitals)
admin.site.register(GrowthMeasurement)


class VaccinationScheduleRuleInline(admin.TabularInline):
    model = VaccinationScheduleRule
    extra = 1


@admin.register(VaccinationSchedule)
class VaccinationScheduleAdmin(admin.ModelAdmin):
    list_display = ["name", "owner_hospital_id", "is_template", "active", "updated_at"]
    search_fields = ["name"]
    list_filter = ["is_template", "active"]
    inlines = [VaccinationScheduleRuleInline]
