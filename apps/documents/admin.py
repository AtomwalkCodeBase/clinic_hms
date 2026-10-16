from django.contrib import admin

from apps.documents.models import ClinicalEvent, GrowthMeasurement, LabResult, SharedAllergy, Vitals, Schedule, ScheduleRule

from apps.documents.models import DocumentBatch, DocumentExtraction, MedicalDocument, DocumentClassification


@admin.register(DocumentBatch)
class DocumentBatchAdmin(admin.ModelAdmin):
    list_display = ["id", "patient", "created_at"]
    search_fields = ["patient__awpid"]


class DocumentExtractionInline(admin.StackedInline):
    model = DocumentExtraction
    extra = 0
    readonly_fields = ["extracted_text", "engine", "normalised"]
    can_delete = False


class DocumentClassificationInline(admin.StackedInline):
    model = DocumentClassification
    extra = 0
    can_delete = False


@admin.register(MedicalDocument)
class MedicalDocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "patient", "file_name", "doc_classification", "status", "created_at"]
    list_filter = ["status", "doc_classification", "created_by_type"]
    search_fields = ["patient__awpid", "file_name"]
    readonly_fields = ["error_message", "created_at"]
    inlines = [DocumentExtractionInline, DocumentClassificationInline]


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


class ScheduleRuleInline(admin.TabularInline):
    model = ScheduleRule
    extra = 1


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ["name", "owner_hospital_id", "is_template", "active", "updated_at"]
    search_fields = ["name"]
    list_filter = ["is_template", "active"]
    inlines = [ScheduleRuleInline]
