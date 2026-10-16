from django.contrib import admin

from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["awpid", "full_name", "date_of_birth", "gender", "created_at"]
    search_fields = ["awpid", "full_name", "email"]
    readonly_fields = ["awpid", "mobile", "created_at"]
