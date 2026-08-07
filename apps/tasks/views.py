from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.response import success, created, error, not_found
from core.permissions import IsHospitalStaff
from .serializers import TaskSerializer
from .models import Task


class TaskListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        qs = Task.objects.using(request.tenant_db).order_by("-created_at")
        if s := request.query_params.get("status"):
            qs = qs.filter(status=s)
        return success(data=TaskSerializer(qs[:50], many=True).data)

    def post(self, request):
        s = TaskSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        task = Task.objects.using(request.tenant_db).create(
            created_by=request.user,
            **{k: v for k, v in s.validated_data.items() if k != "assignments"},
        )
        return created(data=TaskSerializer(task).data)


class TaskCompleteView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def post(self, request, pk):
        try:
            task = Task.objects.using(request.tenant_db).get(pk=pk)
        except Task.DoesNotExist:
            return not_found("Task not found.")
        task.status       = "done"
        task.completed_at = timezone.now()
        task.save(using=request.tenant_db, update_fields=["status", "completed_at"])
        return success(message="Task marked done.")
