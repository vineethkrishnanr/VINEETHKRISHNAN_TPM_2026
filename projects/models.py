from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_projects"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.name


class ProjectMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MEMBER = "member", "Member"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_memberships"
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="uniq_project_member"),
            models.CheckConstraint(
                condition=Q(role__in=["owner", "member"]), name="project_member_role_valid"
            ),
        ]

    def __str__(self):
        return f"{self.user_id} in {self.project_id} ({self.role})"


class TaskStatus(models.TextChoices):
    TODO = "todo", "To Do"
    IN_PROGRESS = "in_progress", "In Progress"
    IN_REVIEW = "in_review", "In Review"
    DONE = "done", "Done"


class TaskPriority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


# Which status can move to which.
ALLOWED_TRANSITIONS = {
    TaskStatus.TODO.value: {TaskStatus.IN_PROGRESS.value},
    TaskStatus.IN_PROGRESS.value: {
        TaskStatus.TODO.value,
        TaskStatus.IN_REVIEW.value,
        TaskStatus.DONE.value,
    },
    TaskStatus.IN_REVIEW.value: {TaskStatus.IN_PROGRESS.value, TaskStatus.DONE.value},
    TaskStatus.DONE.value: {TaskStatus.IN_PROGRESS.value},  # re-open
}


class ActiveTaskManager(models.Manager):
    """Default manager: hides soft-deleted tasks."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Task(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=TaskStatus.choices, default=TaskStatus.TODO
    )
    priority = models.CharField(
        max_length=10, choices=TaskPriority.choices, default=TaskPriority.MEDIUM
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tasks",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_tasks",
    )
    due_date = models.DateField(null=True, blank=True)

    # soft delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ActiveTaskManager()  # excludes soft-deleted rows
    all_objects = models.Manager()  # includes everything

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["project", "status"], name="task_proj_status_idx"),
            models.Index(fields=["project", "assignee"], name="task_proj_assignee_idx"),
            models.Index(fields=["project", "due_date"], name="task_proj_due_idx"),
            models.Index(fields=["project", "is_deleted"], name="task_proj_deleted_idx"),
            models.Index(fields=["priority"], name="task_priority_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["todo", "in_progress", "in_review", "done"]),
                name="task_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(priority__in=["low", "medium", "high", "urgent"]),
                name="task_priority_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_deleted=False, deleted_at__isnull=True)
                    | Q(is_deleted=True, deleted_at__isnull=False)
                ),
                name="task_soft_delete_consistent",
            ),
        ]

    def __str__(self):
        return self.title

    def can_transition_to(self, new_status):
        return new_status == self.status or new_status in ALLOWED_TRANSITIONS.get(
            self.status, set()
        )

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_comments"
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["task", "created_at"], name="comment_task_created_idx")]

    def __str__(self):
        return f"Comment {self.pk} on task {self.task_id}"


class TaskActivity(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        STATUS_CHANGED = "status_changed", "Status changed"
        ASSIGNED = "assigned", "Assigned"
        COMMENTED = "commented", "Commented"
        DELETED = "deleted", "Deleted"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="task_activities",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    field = models.CharField(max_length=50, blank=True)
    old_value = models.CharField(max_length=255, blank=True)
    new_value = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "task activities"
        indexes = [models.Index(fields=["task", "created_at"], name="activity_task_created_idx")]

    def __str__(self):
        return f"{self.action} on task {self.task_id}"
