from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from django_filters.rest_framework import DjangoFilterBackend

from .filters import TaskFilter
from .models import Project, ProjectMember, Task, TaskActivity, TaskComment, TaskStatus
from .permissions import IsProjectOwnerOrReadOnly
from .serializers import (
    AddMemberSerializer,
    ProjectMemberSerializer,
    ProjectSerializer,
    RegisterSerializer,
    TaskActivitySerializer,
    TaskBriefSerializer,
    TaskCommentSerializer,
    TaskSerializer,
    UserSerializer,
)


class ProjectScopedMixin:
    """Resolves /projects/<project_pk>/... and enforces membership.

    Non-members get a 404 so project existence is not leaked.
    """

    def get_project(self):
        if not hasattr(self, "_project"):
            qs = Project.objects.filter(memberships__user=self.request.user)
            self._project = get_object_or_404(qs, pk=self.kwargs["project_pk"])
        return self._project


# ---------------------------------------------------------------- Auth
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "tokens": {"refresh": str(refresh), "access": str(refresh.access_token)},
            },
            status=status.HTTP_201_CREATED,
        )


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


# ---------------------------------------------------------------- Projects
class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated, IsProjectOwnerOrReadOnly]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["created_at", "name"]

    def get_queryset(self):
        return (
            Project.objects.filter(memberships__user=self.request.user)
            .select_related("owner")
            .order_by("-created_at", "-id")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        project = serializer.save(owner=self.request.user)
        ProjectMember.objects.create(
            project=project, user=self.request.user, role=ProjectMember.Role.OWNER
        )

    @action(detail=True, methods=["get"], url_path="dashboard")
    def dashboard(self, request, pk=None):
        project = self.get_object()
        today = timezone.localdate()
        tasks = Task.objects.filter(project=project)

        by_status = {value: 0 for value in TaskStatus.values}
        for row in tasks.values("status").annotate(total=Count("id")).order_by():
            by_status[row["status"]] = row["total"]

        overdue_qs = (
            tasks.filter(due_date__lt=today)
            .exclude(status=TaskStatus.DONE)
            .select_related("assignee")
            .order_by("due_date", "id")
        )

        assigned = Q(user__assigned_tasks__project=project, user__assigned_tasks__is_deleted=False)
        members = (
            ProjectMember.objects.filter(project=project)
            .select_related("user")
            .annotate(
                total_tasks=Count("user__assigned_tasks", filter=assigned),
                open_tasks=Count(
                    "user__assigned_tasks",
                    filter=assigned & ~Q(user__assigned_tasks__status=TaskStatus.DONE),
                ),
            )
            .order_by("joined_at", "id")
        )

        return Response(
            {
                "project": {"id": project.id, "name": project.name},
                "total_tasks": tasks.count(),
                "tasks_by_status": by_status,
                "overdue": {
                    "count": overdue_qs.count(),
                    "tasks": TaskBriefSerializer(overdue_qs, many=True).data,
                },
                "tasks_per_member": [
                    {
                        "user_id": m.user_id,
                        "username": m.user.username,
                        "role": m.role,
                        "total_tasks": m.total_tasks,
                        "open_tasks": m.open_tasks,
                    }
                    for m in members
                ],
                "unassigned_tasks": tasks.filter(assignee__isnull=True).count(),
            }
        )


# ---------------------------------------------------------------- Members
class MemberViewSet(
    ProjectScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    lookup_field = "user_id"

    def get_queryset(self):
        return ProjectMember.objects.filter(project=self.get_project()).select_related("user")

    def get_serializer_class(self):
        return AddMemberSerializer if self.action == "create" else ProjectMemberSerializer

    def _require_owner(self):
        if self.get_project().owner_id != self.request.user.id:
            raise PermissionDenied("Only the project owner can manage members.")

    def create(self, request, *args, **kwargs):
        self._require_owner()
        project = self.get_project()
        serializer = AddMemberSerializer(data=request.data, context={"project": project})
        serializer.is_valid(raise_exception=True)
        member = ProjectMember.objects.create(
            project=project, user=serializer.user, role=ProjectMember.Role.MEMBER
        )
        return Response(ProjectMemberSerializer(member).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def perform_destroy(self, instance):
        self._require_owner()
        if instance.role == ProjectMember.Role.OWNER:
            raise ValidationError("The project owner cannot be removed.")
        # un-assign their tasks in this project
        Task.objects.filter(project=instance.project, assignee=instance.user).update(assignee=None)
        instance.delete()


# ---------------------------------------------------------------- Tasks
class TaskViewSet(ProjectScopedMixin, viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = TaskFilter
    search_fields = ["title"]
    ordering_fields = ["due_date", "created_at", "updated_at", "title"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Task.objects.filter(project=self.get_project()).select_related(
            "assignee", "created_by"
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["project"] = self.get_project()
        return context

    @transaction.atomic
    def perform_destroy(self, instance):
        user = self.request.user
        if user.id not in (self.get_project().owner_id, instance.created_by_id):
            raise PermissionDenied("Only the project owner or the task creator can delete a task.")
        instance.soft_delete()
        TaskActivity.objects.create(task=instance, actor=user, action=TaskActivity.Action.DELETED)


class TaskChildMixin(ProjectScopedMixin):
    def get_task(self):
        if not hasattr(self, "_task"):
            qs = Task.objects.filter(project=self.get_project())
            self._task = get_object_or_404(qs, pk=self.kwargs["task_pk"])
        return self._task


class CommentViewSet(
    TaskChildMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TaskCommentSerializer

    def get_queryset(self):
        return TaskComment.objects.filter(task=self.get_task()).select_related("author")

    @transaction.atomic
    def perform_create(self, serializer):
        task = self.get_task()
        serializer.save(task=task, author=self.request.user)
        TaskActivity.objects.create(
            task=task, actor=self.request.user, action=TaskActivity.Action.COMMENTED
        )

    def perform_destroy(self, instance):
        user = self.request.user
        if user.id not in (instance.author_id, self.get_project().owner_id):
            raise PermissionDenied("Only the author or the project owner can delete a comment.")
        instance.delete()


class ActivityViewSet(TaskChildMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = TaskActivitySerializer

    def get_queryset(self):
        return TaskActivity.objects.filter(task=self.get_task()).select_related("actor")