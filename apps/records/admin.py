from django.contrib import admin

from .models import DocumentBatch, DocumentClassification, MedicalDocument


@admin.register(DocumentClassification)
class DocumentClassificationAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "keywords", "is_active", "is_staff_only", "updated_at"]
    list_editable = ["keywords", "is_active"]


@admin.register(DocumentBatch)
class DocumentBatchAdmin(admin.ModelAdmin):
    list_display = ["id", "awpid", "total_files", "processed_files", "failed_files", "status", "created_at"]
    search_fields = ["awpid__awpid"]


@admin.register(MedicalDocument)
class MedicalDocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "awpid", "title", "classification", "classification_source", "status", "score", "created_at"]
    list_filter = ["status", "classification_source", "classification", "uploaded_by"]
    search_fields = ["awpid__awpid", "title", "original_file_name"]
    readonly_fields = ["classification_details", "error", "created_at", "updated_at"]
