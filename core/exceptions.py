"""
core/exceptions.py
------------------
Custom exception handler for Atomwalk HMS.
Wraps all DRF exceptions in our standard { success, message, errors } shape.
Register in settings: REST_FRAMEWORK.EXCEPTION_HANDLER = 'core.exceptions.custom_exception_handler'
"""

import logging
from rest_framework.views import exception_handler
from rest_framework import status

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Intercepts every DRF exception and returns a standardized error response.
    Unhandled exceptions (500s) are logged and returned as generic server errors.
    """
    # Call DRF's default handler first
    response = exception_handler(exc, context)

    if response is not None:
        # Reshape DRF's error response into our standard format
        error_data = response.data

        # DRF sometimes returns a list (e.g. non-field errors), normalize it
        if isinstance(error_data, list):
            message = " ".join(str(e) for e in error_data)
            errors = {}
        elif isinstance(error_data, dict):
            # Extract a human-readable message from the first field error
            first_key = next(iter(error_data), None)
            if first_key == "detail":
                message = str(error_data["detail"])
                errors = {}
            else:
                message = "Validation failed. Please check the highlighted fields."
                errors = error_data
        else:
            message = str(error_data)
            errors = {}

        response.data = {
            "success": False,
            "message": message,
            "errors": errors,
        }
    else:
        # Unhandled exception — log it and return a 500
        logger.exception("Unhandled exception in %s", context.get("view", "unknown view"))

    return response
