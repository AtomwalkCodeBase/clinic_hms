from rest_framework import serializers

MB = 1024 * 1024
MAX_FILE_BYTES = 5 * MB
MAX_TOTAL_BYTES = 250 * MB
MAX_FILES = 50


def size_text(n):
    """A size the way a patient reads it: "7.2 MB", "300 KB"."""
    if n >= MB:
        return f"{round(n / MB, 1):g} MB"
    return f"{n // 1024} KB" if n >= 1024 else f"{n} bytes"


class UploadSerializer(serializers.Serializer):
    """Size only — the file's content is checked by the extraction job, so one bad file never blocks the rest. A file that
    is empty or over the per-file limit is left out and listed in `skipped` with its reason; the others go through."""
    files = serializers.ListField(child=serializers.FileField(allow_empty_file=True), allow_empty=False)    # an empty file is skipped below, not a failure of the request

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skipped = []

    def validate_files(self, files):
        if len(files) > MAX_FILES:
            raise serializers.ValidationError(f"Upload at most {MAX_FILES} files at a time.")
        kept = []
        for f in files:
            if f.size == 0:
                self.skipped.append({"name": f.name, "reason": "The file is empty (0 KB)."})
            elif f.size > MAX_FILE_BYTES:
                self.skipped.append({"name": f.name, "reason": f"The file is {size_text(f.size)}; the limit is {size_text(MAX_FILE_BYTES)} per file."})
            else:
                kept.append(f)
        if not kept:
            raise serializers.ValidationError([f"{s['name']} — {s['reason']}" for s in self.skipped])
        if sum(f.size for f in kept) > MAX_TOTAL_BYTES:
            raise serializers.ValidationError(f"The upload is over {size_text(MAX_TOTAL_BYTES)} in total.")
        return [(f, f.read()) for f in kept]


class DecisionSerializer(serializers.Serializer):
    document_id = serializers.IntegerField(min_value=1)
    document_type = serializers.CharField(max_length=50)


class SubmitSerializer(serializers.Serializer):
    """The patient's final answers: one type per file. The type itself is checked per file in services.submit_decisions,"""
    decisions = serializers.ListField(child=DecisionSerializer(), allow_empty=False, max_length=100)
