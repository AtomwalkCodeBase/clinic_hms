from django.contrib import admin

from apps.atomwalk.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["awpid", "full_name", "date_of_birth", "gender", "created_at"]
    search_fields = ["awpid", "full_name", "email"]
    readonly_fields = ["awpid", "mobile_hash", "created_at", "updated_at"]
