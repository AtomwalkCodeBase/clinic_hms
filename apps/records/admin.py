from django.contrib import admin

from .models import DocumentBatch, DocumentText, MedicalDocument, PatientDocumentClassification


@admin.register(DocumentBatch)
class DocumentBatchAdmin(admin.ModelAdmin):
    list_display = ["id", "patient", "total_files", "processed_files", "failed_files", "status", "created_at"]
    search_fields = ["patient__awpid"]


class DocumentTextInline(admin.StackedInline):
    model = DocumentText
    extra = 0
    readonly_fields = ["extracted_text", "engine", "created_at"]
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
    inlines = [DocumentTextInline, PatientDocumentClassificationInline]
