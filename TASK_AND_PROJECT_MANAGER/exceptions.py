from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    """Return every error in one shape:

    {"error": {"code": "...", "status": 400, "message": "...", "details": {...} | null}}
    """
    response = exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    details = None

    if isinstance(exc, ValidationError):
        code = "validation_error"
        message = "Invalid input."
        details = data
    else:
        codes = exc.get_codes() if hasattr(exc, "get_codes") else "error"
        code = codes if isinstance(codes, str) else "error"
        if isinstance(data, dict) and "detail" in data:
            message = str(data["detail"])
        else:
            message = "Request failed."
            details = data

    response.data = {
        "error": {
            "code": code,
            "status": response.status_code,
            "message": message,
            "details": details,
        }
    }
    return response
