"""core/api/response.py"""

from rest_framework.response import Response
from rest_framework import status as http_status


def success(data=None, message="", status=http_status.HTTP_200_OK):
    """Return a successful API response."""
    return Response(
        {
            "success": True,
            "message": message,
            "data": data,
        },
        status=status,
    )


def created(data=None, message="Created successfully"):
    """Shortcut for 201 Created responses."""
    return success(data=data, message=message, status=http_status.HTTP_201_CREATED)


def error(message="An error occurred", errors=None, status=http_status.HTTP_400_BAD_REQUEST):
    """Return an error API response."""
    return Response(
        {
            "success": False,
            "message": message,
            "errors": errors or {},
        },
        status=status,
    )


def not_found(message="Resource not found"):
    """Shortcut for 404 Not Found responses."""
    return error(message=message, status=http_status.HTTP_404_NOT_FOUND)


def forbidden(message="You do not have permission to perform this action"):
    """Shortcut for 403 Forbidden responses."""
    return error(message=message, status=http_status.HTTP_403_FORBIDDEN)


def server_error(message="Internal server error"):
    """Shortcut for 500 responses (use sparingly — let exception handler catch)."""
    return error(message=message, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
