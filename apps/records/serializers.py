from rest_framework import serializers

from core.file_validation import FileValidationError, validate_bytes

MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024


class UploadSerializer(serializers.Serializer):
    """Checks EVERY file before anything goes to S3; one bad file rejects the whole upload."""
    files = serializers.ListField(child=serializers.FileField(), allow_empty=False)

    def validate_files(self, files):
        if sum(f.size for f in files) > MAX_TOTAL_BYTES:
            raise serializers.ValidationError("The upload is over 200 MB in total.")
        checked = []
        for f in files:
            if f.size > MAX_FILE_BYTES:
                raise serializers.ValidationError(f"{f.name} is over 12 MB.")
            raw = f.read()
            try:
                mime = validate_bytes(raw)          # real PDF / JPEG / PNG, by content
            except FileValidationError as exc:
                raise serializers.ValidationError(f"{f.name}: {exc}")
            checked.append((f, raw, mime))
        return checked
