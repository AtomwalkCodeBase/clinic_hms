"""
apps/notifications/models.py
-----------------------------
Tables: NotificationTemplate, NotificationLog, DeviceToken

feat_whatsapp gate enforced at API view level for WhatsApp channel.
Templates are tenant-configurable (no hardcoded message text).
"""

from django.db import models
from apps.org.models import StaffUser
from apps.patients.models import Patient


class NotificationTemplate(models.Model):
    """
    Tenant-configured notification template.
    Variables in body use {{variable_name}} placeholders.
    """
    CHANNEL_CHOICES = [
        ("sms",       "SMS"),
        ("whatsapp",  "WhatsApp"),    # feat_whatsapp required
        ("email",     "Email"),
        ("push",      "Push"),
    ]

    EVENT_CHOICES = [
        ("appointment_booked",    "Appointment Booked"),
        ("appointment_reminder",  "Appointment Reminder"),
        ("appointment_cancelled", "Appointment Cancelled"),
        ("report_ready",          "Lab Report Ready"),
        ("prescription_ready",    "Prescription Ready"),
        ("invoice_issued",        "Invoice Issued"),
        ("payment_received",      "Payment Received"),
        ("queue_called",          "Queue Token Called"),
        ("custom",                "Custom"),
    ]

    event       = models.CharField(max_length=50, choices=EVENT_CHOICES)
    channel     = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    subject     = models.CharField(max_length=200, blank=True)  # for email
    body        = models.TextField()
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "notifications"
        db_table  = "notification_template"
        unique_together = [("event", "channel")]

    def __str__(self):
        return f"{self.event} via {self.channel}"


class NotificationLog(models.Model):
    """
    Delivery log for every notification attempt.
    Keeps an audit trail regardless of success/failure.
    """
    STATUS_CHOICES = [
        ("queued",    "Queued"),
        ("sent",      "Sent"),
        ("delivered", "Delivered"),
        ("failed",    "Failed"),
    ]

    template    = models.ForeignKey(NotificationTemplate, on_delete=models.SET_NULL,
                                    null=True, blank=True)
    patient     = models.ForeignKey(Patient, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="notifications")
    recipient   = models.CharField(max_length=200)  # phone or email
    channel     = models.CharField(max_length=20)
    body        = models.TextField()                 # rendered body (after variable substitution)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued", db_index=True)
    provider_ref= models.CharField(max_length=200, blank=True)  # external message ID
    error       = models.TextField(blank=True)
    sent_at     = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "notifications"
        db_table  = "notification_log"
        ordering  = ["-created_at"]


class DeviceToken(models.Model):
    """
    Push notification device token per patient.
    platform: fcm (Android/web) or apns (iOS).
    """
    PLATFORM_CHOICES = [("fcm", "FCM"), ("apns", "APNS")]

    patient     = models.ForeignKey(Patient, on_delete=models.CASCADE,
                                    related_name="device_tokens")
    token       = models.TextField(unique=True)
    platform    = models.CharField(max_length=10, choices=PLATFORM_CHOICES)
    is_active   = models.BooleanField(default=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "notifications"
        db_table  = "device_token"
