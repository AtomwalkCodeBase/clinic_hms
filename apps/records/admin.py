from django.contrib import admin

from .models import ClassificationRule, SharedDocument, UploadBatch


@admin.register(ClassificationRule)
class ClassificationRuleAdmin(admin.ModelAdmin):
    list_display = ["doc_type", "keywords", "is_active", "updated_at"]
    list_editable = ["keywords", "is_active"]


@admin.register(UploadBatch)
class UploadBatchAdmin(admin.ModelAdmin):
    list_display = ["id", "awpid", "total_files", "created_at"]
    search_fields = ["awpid"]


@admin.register(SharedDocument)
class SharedDocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "awpid", "title", "doc_type", "processing_status", "score", "method", "created_at"]
    list_filter = ["processing_status", "method", "doc_type", "uploaded_by"]
    search_fields = ["awpid", "title", "file_name"]
    readonly_fields = ["extracted_text", "error", "created_at", "updated_at"]
