from rest_framework import serializers

MAX_FILE_BYTES = 250 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024
MAX_FILES = 50


class UploadSerializer(serializers.Serializer):
    """Size only — the file's content is checked by the extraction job, so one bad file never blocks the rest."""
    files = serializers.ListField(child=serializers.FileField(), allow_empty=False)

    def validate_files(self, files):
        if len(files) > MAX_FILES:
            raise serializers.ValidationError(f"Upload at most {MAX_FILES} files at a time.")
        if sum(f.size for f in files) > MAX_TOTAL_BYTES:
            raise serializers.ValidationError("The upload is over 250 MB in total.")
        for f in files:
            if f.size == 0:
                raise serializers.ValidationError(f"{f.name} is empty (0 KB).")
            if f.size > MAX_FILE_BYTES:
                raise serializers.ValidationError(f"{f.name} is over 250 MB.")
        return [(f, f.read()) for f in files]
