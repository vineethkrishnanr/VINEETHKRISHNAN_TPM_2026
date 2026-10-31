from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import (
    ALLOWED_TRANSITIONS,
    Project,
    ProjectMember,
    Task,
    TaskActivity,
    TaskComment,
    TaskStatus,
)

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "first_name", "last_name"]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class ProjectSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "name", "description", "owner", "member_count", "created_at", "updated_at"]
        read_only_fields = ["id", "owner", "member_count", "created_at", "updated_at"]

    def get_member_count(self, obj) -> int:
        return obj.memberships.count()


class ProjectMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = ProjectMember
        fields = ["id", "user", "role", "joined_at"]
        read_only_fields = fields


class AddMemberSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        user = User.objects.filter(email__iexact=value).first()
        if user is None:
            raise serializers.ValidationError("No registered user with this email.")
        if ProjectMember.objects.filter(project=self.context["project"], user=user).exists():
            raise serializers.ValidationError("This user is already a member of the project.")
        self.user = user
        return value


TRACKED_FIELDS = ["title", "description", "status", "priority", "assignee", "due_date"]


def _display(value):
    if value is None:
        return ""
    if hasattr(value, "get_username"):
        return value.get_username()
    return str(value)[:255]


class TaskSerializer(serializers.ModelSerializer):
    assignee_detail = UserSerializer(source="assignee", read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id", "project", "title", "description", "status", "priority",
            "assignee", "assignee_detail", "due_date", "is_overdue",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "project", "created_by", "created_at", "updated_at"]

    def get_is_overdue(self, obj) -> bool:
        return bool(
            obj.due_date and obj.due_date < timezone.localdate() and obj.status != TaskStatus.DONE
        )

    def validate_assignee(self, value):
        if value is not None and not ProjectMember.objects.filter(
            project=self.context["project"], user=value
        ).exists():
            raise serializers.ValidationError("Assignee must be a member of this project.")
        return value

    def validate(self, attrs):
        new_status = attrs.get("status")
        if self.instance is None:
            if new_status and new_status != TaskStatus.TODO:
                raise serializers.ValidationError({"status": "A new task must start as 'todo'."})
        elif new_status and new_status != self.instance.status:
            allowed = ALLOWED_TRANSITIONS[self.instance.status]
            if new_status not in allowed:
                raise serializers.ValidationError(
                    {
                        "status": (
                            f"Cannot move from '{self.instance.status}' to '{new_status}'. "
                            f"Allowed: {', '.join(sorted(allowed))}."
                        )
                    }
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user = self.context["request"].user
        task = Task.objects.create(
            project=self.context["project"], created_by=user, **validated_data
        )
        TaskActivity.objects.create(
            task=task, actor=user, action=TaskActivity.Action.CREATED, new_value=task.title[:255]
        )
        if task.assignee_id:
            TaskActivity.objects.create(
                task=task, actor=user, action=TaskActivity.Action.ASSIGNED,
                field="assignee", new_value=_display(task.assignee),
            )
        return task

    @transaction.atomic
    def update(self, instance, validated_data):
        user = self.context["request"].user
        old = {f: getattr(instance, f) for f in TRACKED_FIELDS}
        instance = super().update(instance, validated_data)

        activities = []
        for field in TRACKED_FIELDS:
            new = getattr(instance, field)
            if old[field] == new:
                continue
            if field == "status":
                action = TaskActivity.Action.STATUS_CHANGED
            elif field == "assignee":
                action = TaskActivity.Action.ASSIGNED
            else:
                action = TaskActivity.Action.UPDATED
            activities.append(
                TaskActivity(
                    task=instance, actor=user, action=action, field=field,
                    old_value=_display(old[field]), new_value=_display(new),
                )
            )
        TaskActivity.objects.bulk_create(activities)
        return instance


class TaskBriefSerializer(serializers.ModelSerializer):
    assignee = serializers.CharField(source="assignee.username", default=None, read_only=True)

    class Meta:
        model = Task
        fields = ["id", "title", "status", "priority", "due_date", "assignee"]
        read_only_fields = fields


class TaskCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = TaskComment
        fields = ["id", "author", "body", "created_at"]
        read_only_fields = ["id", "author", "created_at"]


class TaskActivitySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", default=None, read_only=True)

    class Meta:
        model = TaskActivity
        fields = ["id", "actor", "action", "field", "old_value", "new_value", "created_at"]
        read_only_fields = fields
