from django.urls import path
from .views import TaskListCreateView, TaskCompleteView

urlpatterns = [
    path("",              TaskListCreateView.as_view(), name="task-list"),
    path("<int:pk>/complete/", TaskCompleteView.as_view(), name="task-complete"),
]
