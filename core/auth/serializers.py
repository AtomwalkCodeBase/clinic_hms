"""core/auth/serializers.py — Login and auth serializers."""
from rest_framework import serializers


class StaffLoginSerializer(serializers.Serializer):
    """Staff login — two supported shapes:"""
    mobile      = serializers.CharField(required=False, allow_blank=True)
    hospital_code   = serializers.CharField(required=False, allow_blank=True)
    employee_id = serializers.CharField(required=False, allow_blank=True)
    password    = serializers.CharField(write_only=True)

    def validate(self, data):
        has_mobile = bool(data.get("mobile"))
        has_employee_login = bool(data.get("hospital_code")) and bool(data.get("employee_id"))
        if not has_mobile and not has_employee_login:
            raise serializers.ValidationError(
                "Provide a mobile number, or your hospital code and employee ID."
            )
        return data


class PlatformLoginSerializer(serializers.Serializer):
    """Platform admin logs in with username or email + password (no hospital_code)."""
    username = serializers.CharField()  # accepts username OR email
    password = serializers.CharField(write_only=True)


class PatientLoginSerializer(serializers.Serializer):
    awpid    = serializers.CharField()
    password = serializers.CharField(write_only=True)


class SetupPasswordSerializer(serializers.Serializer):
    invite_token     = serializers.CharField()
    new_password     = serializers.CharField(min_length=8, write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        return data


class ChangePasswordSerializer(serializers.Serializer):
    # Only required for a voluntary change (see ChangePasswordView) — the
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    new_password      = serializers.CharField(min_length=8, write_only=True)
    confirm_password  = serializers.CharField(write_only=True)

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        return data


class PermissionsSerializer(serializers.Serializer):
    feat_whatsapp     = serializers.BooleanField()
    feat_multi_branch = serializers.BooleanField()
    feat_ai_voice     = serializers.BooleanField()
    feat_patient_app  = serializers.BooleanField()
    feat_analytics    = serializers.BooleanField()
    feat_video        = serializers.BooleanField()
    feat_face_recog   = serializers.BooleanField()
    license_tier      = serializers.CharField()
    subscription_status = serializers.CharField()
