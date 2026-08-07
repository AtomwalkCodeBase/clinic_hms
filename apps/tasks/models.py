"""
apps/tasks/models.py
---------------------
Tables: Task, TaskAssignment

Workflow tasks for internal staff coordination — nursing instructions,
housekeeping, supply requests, administrative tasks.
"""

from django.db import models
from apps.org.models import StaffUser, Branch, Department
from apps.patients.models import Patient


class Task(models.Model):
    PRIORITY_CHOICES = [
        ("low",    "Low"),
        ("medium", "Medium"),
        ("high",   "High"),
        ("urgent", "Urgent"),
    ]

    STATUS_CHOICES = [
        ("pending",     "Pending"),
        ("in_progress", "In Progress"),
        ("done",        "Done"),
        ("cancelled",   "Cancelled"),
    ]

    CATEGORY_CHOICES = [
        ("nursing",       "Nursing"),
        ("housekeeping",  "Housekeeping"),
        ("supply",        "Supply Request"),
        ("admin",         "Administrative"),
        ("follow_up",     "Follow-Up"),
        ("other",         "Other"),
    ]

    title           = models.CharField(max_length=200)
    description     = models.TextField(blank=True)
    category        = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other")
    priority        = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    branch          = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="tasks")
    department      = models.ForeignKey(Department, on_delete=models.SET_NULL,
                                        null=True, blank=True)
    patient         = models.ForeignKey(Patient, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="tasks")
    created_by      = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="tasks_created")
    due_at          = models.DateTimeField(null=True, blank=True)
    completed_at    = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "tasks"
        db_table  = "task"
        ordering  = ["-priority", "due_at"]

    def __str__(self):
        return f"[{self.priority.upper()}] {self.title} ({self.status})"


class TaskAssignment(models.Model):
    """Links a task to one or more staff members."""
    task        = models.ForeignKey(Task, on_delete=models.CASCADE,
                                    related_name="assignments")
    assignee    = models.ForeignKey(StaffUser, on_delete=models.CASCADE,
                                    related_name="task_assignments")
    assigned_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="tasks_assigned")
    assigned_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "tasks"
        db_table  = "task_assignment"
        unique_together = [("task", "assignee")]

    def __str__(self):
        return f"Task#{self.task_id} → {self.assignee.get_full_name()}"
