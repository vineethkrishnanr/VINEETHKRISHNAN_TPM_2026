from django.contrib import admin

from .models import Project, ProjectMember, Task, TaskActivity, TaskComment


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "owner", "created_at")
    search_fields = ("name",)


@admin.register(ProjectMember)
class ProjectMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "user", "role")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "project", "status", "priority", "assignee", "due_date", "is_deleted")
    list_filter = ("status", "priority", "is_deleted")
    search_fields = ("title",)

    def get_queryset(self, request):
        return Task.all_objects.all()  # show soft-deleted tasks in admin too


admin.site.register(TaskComment)
admin.site.register(TaskActivity)
