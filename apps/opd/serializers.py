from datetime import date as _date
from rest_framework import serializers
from .models import Appointment, Vitals, OPDEncounter, Prescription, PrescriptionItem, PrescriptionFavourite


class VitalsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vitals
        exclude = ["appointment"]
        read_only_fields = ["id", "recorded_at", "bmi"]


class AppointmentSerializer(serializers.ModelSerializer):
    vitals        = VitalsSerializer(read_only=True)
    has_encounter = serializers.SerializerMethodField()
    encounter     = serializers.SerializerMethodField()
    patient_name  = serializers.SerializerMethodField()
    patient_uhid  = serializers.SerializerMethodField()
    patient_age   = serializers.SerializerMethodField()
    patient_gender = serializers.SerializerMethodField()
    is_dependent  = serializers.SerializerMethodField()
    guardian_name = serializers.SerializerMethodField()
    guardian_relation = serializers.SerializerMethodField()
    awpid         = serializers.CharField(source="patient_awpid", read_only=True)
    visit_type    = serializers.CharField(source="appointment_type", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id", "patient_id", "patient_awpid", "awpid",
            "patient_name", "patient_uhid", "patient_age", "patient_gender",
            "is_dependent", "guardian_name", "guardian_relation",
            "doctor_user_id", "doctor_name",
            "appointment_type", "visit_type", "status",
            "scheduled_date", "scheduled_time",
            "token_number", "chief_complaint", "notes", "payment_preference",
            "room_id", "room_name", "floor",
            "checked_in_at", "started_at", "completed_at",
            "vitals", "has_encounter", "encounter", "created_at",
        ]
        read_only_fields = ["id", "token_number", "created_at"]

    def get_has_encounter(self, obj):
        return hasattr(obj, "encounter")

    def get_encounter(self, obj):
        try:
            enc = obj.encounter
            return {"id": str(enc.id), "status": enc.status}
        except Exception:
            return None

    def _get_patient(self, obj):
        try:
            from apps.patients.models import Patient
            db = self.context.get("db") or (getattr(obj, "_state", None) and obj._state.db)
            if db:
                return Patient.objects.using(db).filter(uuid=obj.patient_id).first()
        except Exception:
            pass
        return None

    def get_patient_name(self, obj):
        p = self._get_patient(obj)
        return p.full_name if p else ""

    def get_patient_uhid(self, obj):
        p = self._get_patient(obj)
        return p.uhid if p else ""

    def get_patient_age(self, obj):
        p = self._get_patient(obj)
        if not p or not p.date_of_birth:
            return None
        today = _date.today()
        dob = p.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    def get_patient_gender(self, obj):
        p = self._get_patient(obj)
        return p.gender if p else ""

    def get_is_dependent(self, obj):
        p = self._get_patient(obj)
        return bool(p and p.is_dependent)

    def get_guardian_name(self, obj):
        p = self._get_patient(obj)
        return p.guardian_name if p else ""

    def get_guardian_relation(self, obj):
        p = self._get_patient(obj)
        return p.guardian_relation if p else ""


class AppointmentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = [
            "patient_id", "patient_awpid", "doctor_user_id", "doctor_name",
            "appointment_type", "scheduled_date", "scheduled_time", "chief_complaint", "notes",
        ]

    def validate(self, data):
        if not data.get("patient_id") or not data.get("patient_awpid"):
            raise serializers.ValidationError("patient_id and patient_awpid are required.")
        return data


class AppointmentStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Appointment.STATUS_CHOICES)
    notes = serializers.CharField(required=False, allow_blank=True)


class PrescriptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionItem
        exclude = ["prescription"]
        read_only_fields = ["id"]


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        fields = ["id", "rx_number", "encounter_id", "patient_id", "doctor_user_id",
                  "status", "notes", "items", "patient_choice", "payment_preference",
                  "payment_status", "invoice_id", "created_at", "updated_at"]
        read_only_fields = ["id", "rx_number", "created_at", "updated_at", "invoice_id"]


class OPDEncounterSerializer(serializers.ModelSerializer):
    prescription = PrescriptionSerializer(read_only=True)
    vitals       = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    patient_uhid = serializers.SerializerMethodField()
    patient_pk   = serializers.SerializerMethodField()
    patient_age  = serializers.SerializerMethodField()
    patient_gender = serializers.SerializerMethodField()
    is_dependent = serializers.SerializerMethodField()
    guardian_name = serializers.SerializerMethodField()
    guardian_relation = serializers.SerializerMethodField()
    patient_last_visit = serializers.SerializerMethodField()
    encounter_date = serializers.SerializerMethodField()
    chief_complaint = serializers.SerializerMethodField()

    class Meta:
        model = OPDEncounter
        fields = [
            "id", "appointment_id", "patient_id", "doctor_user_id",
            "patient_name", "patient_uhid", "patient_pk", "patient_age", "patient_gender",
            "is_dependent", "guardian_name", "guardian_relation",
            "patient_last_visit", "encounter_date", "chief_complaint",
            "status", "subjective", "objective", "assessment", "plan",
            "investigations", "advice_to_patient", "follow_up_in_days",
            "diagnoses", "referred_to", "referral_notes",
            "ai_transcript_job_id", "ai_transcript_text",
            "signed_at", "prescription", "vitals", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "signed_at", "created_at", "updated_at"]

    def _patient(self, obj):
        try:
            from apps.patients.models import Patient
            db = getattr(obj._state, "db", None) or self.context.get("db")
            if db:
                return Patient.objects.using(db).filter(uuid=obj.patient_id).first()
        except Exception:
            pass
        return None

    def get_patient_name(self, obj):
        p = self._patient(obj)
        return p.full_name if p else ""

    def get_patient_uhid(self, obj):
        p = self._patient(obj)
        return p.uhid if p else ""

    def get_patient_pk(self, obj):
        # Patient's real numeric id (obj.patient_id is Patient.uuid, not the
        # pk) — the frontend needs this to call /patients/{pk}/history/.
        p = self._patient(obj)
        return p.id if p else None

    def get_patient_age(self, obj):
        p = self._patient(obj)
        if not p or not p.date_of_birth:
            return None
        today = _date.today()
        dob = p.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    def get_patient_gender(self, obj):
        p = self._patient(obj)
        return p.gender if p else ""

    def get_is_dependent(self, obj):
        p = self._patient(obj)
        return bool(p and p.is_dependent)

    def get_guardian_name(self, obj):
        p = self._patient(obj)
        return p.guardian_name if p else ""

    def get_guardian_relation(self, obj):
        p = self._patient(obj)
        return p.guardian_relation if p else ""

    def get_patient_last_visit(self, obj):
        # Most recent OTHER completed visit for this patient at this hospital
        # (excludes the current encounter's own appointment) — real data,
        # used for the "Last visit: ..." line in the clinical summary header.
        p = self._patient(obj)
        db = getattr(obj._state, "db", None) or self.context.get("db")
        if not p or not db:
            return None
        try:
            last = (Appointment.objects.using(db)
                    .filter(patient_id=p.uuid, status=Appointment.STATUS_DONE)
                    .exclude(pk=obj.appointment_id)
                    .order_by("-scheduled_date").first())
            return str(last.scheduled_date) if last else None
        except Exception:
            return None

    def get_encounter_date(self, obj):
        try:
            return str(obj.appointment.scheduled_date)
        except Exception:
            return str(obj.created_at.date())

    def get_chief_complaint(self, obj):
        try:
            return obj.appointment.chief_complaint
        except Exception:
            return ""

    def get_vitals(self, obj):
        try:
            return VitalsSerializer(obj.appointment.vitals).data
        except Exception:
            return None


class OPDEncounterCreateSerializer(serializers.ModelSerializer):
    vitals = VitalsSerializer(required=False)
    # Accept either 'appointment' or 'appointment_id' from the frontend.
    # Both must be declared explicitly — DRF treats FK attnames like
    # 'appointment_id' as read-only otherwise, silently dropping the value.
    appointment    = serializers.UUIDField(write_only=True, required=False)
    appointment_id = serializers.UUIDField(required=False)

    class Meta:
        model = OPDEncounter
        fields = [
            "appointment_id", "appointment", "patient_id", "doctor_user_id",
            "subjective", "objective", "assessment", "plan",
            "investigations", "advice_to_patient", "follow_up_in_days",
            "diagnoses", "referred_to", "referral_notes", "vitals",
        ]

    def validate(self, data):
        # Normalise: if frontend sent 'appointment', map it to 'appointment_id'
        if data.get("appointment") and not data.get("appointment_id"):
            data["appointment_id"] = data.pop("appointment")
        else:
            data.pop("appointment", None)
        if not data.get("appointment_id"):
            raise serializers.ValidationError({"appointment_id": "This field is required."})
        return data

    def create(self, validated_data):
        vitals_data = validated_data.pop("vitals", None)
        db = self.context["db"]
        encounter = OPDEncounter(**validated_data)
        encounter.save(using=db)
        if vitals_data:
            Vitals.objects.using(db).create(appointment=encounter.appointment, **vitals_data)
        return encounter


class PrescriptionFavouriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionFavourite
        fields = "__all__"
        read_only_fields = ["id", "created_at"]
