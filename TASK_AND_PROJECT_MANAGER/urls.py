from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def json_404(request, exception=None):
    return JsonResponse(
        {"error": {"code": "not_found", "status": 404, "message": "Not found.", "details": None}},
        status=404,
    )


def json_500(request):
    return JsonResponse(
        {"error": {"code": "server_error", "status": 500, "message": "Server error.", "details": None}},
        status=500,
    )


handler404 = json_404
handler500 = json_500

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("projects.urls")),
]
