from django.urls import include, path
from rest_framework.routers import DefaultRouter

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    ActivityViewSet,
    CommentViewSet,
    MemberViewSet,
    MeView,
    ProjectViewSet,
    RegisterView,
    TaskViewSet,
)

router = DefaultRouter()
router.register("projects", ProjectViewSet, basename="project")

P = "projects/<int:project_pk>"

urlpatterns = [
    path("", include(router.urls)),
    # auth
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/login/", TokenObtainPairView.as_view(), name="auth-login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("auth/me/", MeView.as_view(), name="auth-me"),
    # members
    path(f"{P}/members/", MemberViewSet.as_view({"get": "list", "post": "create"}), name="project-members"),
    path(f"{P}/members/<int:user_id>/", MemberViewSet.as_view({"delete": "destroy"}), name="project-member-detail"),
    # tasks
    path(f"{P}/tasks/", TaskViewSet.as_view({"get": "list", "post": "create"}), name="task-list"),
    path(
        f"{P}/tasks/<int:pk>/",
        TaskViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}),
        name="task-detail",
    ),
    # comments + activity
    path(f"{P}/tasks/<int:task_pk>/comments/", CommentViewSet.as_view({"get": "list", "post": "create"}), name="task-comments"),
    path(f"{P}/tasks/<int:task_pk>/comments/<int:pk>/", CommentViewSet.as_view({"delete": "destroy"}), name="task-comment-detail"),
    path(f"{P}/tasks/<int:task_pk>/activity/", ActivityViewSet.as_view({"get": "list"}), name="task-activity"),
]
