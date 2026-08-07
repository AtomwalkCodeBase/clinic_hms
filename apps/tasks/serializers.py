from rest_framework import serializers
from .models import Task, TaskAssignment


class TaskAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TaskAssignment
        fields = ["id", "assignee", "assigned_at", "accepted_at"]
        read_only_fields = ["id", "assigned_at"]


class TaskSerializer(serializers.ModelSerializer):
    assignments = TaskAssignmentSerializer(many=True, read_only=True)

    class Meta:
        model  = Task
        fields = ["id", "title", "description", "category", "priority", "status",
                  "branch", "department", "patient", "due_at", "completed_at",
                  "created_at", "assignments"]
        read_only_fields = ["id", "created_at", "completed_at"]
