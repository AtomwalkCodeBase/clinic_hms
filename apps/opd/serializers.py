from rest_framework import serializers
from core.utils.age import age_years_months as _age_years_months
from apps.billing.models import OptionList
from apps.opd.models import Appointment, OPDEncounter, Prescription, PrescriptionItem


class VitalsSerializer(serializers.Serializer):
    """The vitals of one visit (kept in Atomwalk, see apps/vitals.py): what a nurse enters, and what the screens read back."""
    recorded_at = serializers.DateTimeField(read_only=True)
    recorded_by_user_id = serializers.UUIDField(read_only=True)
    systolic_bp = serializers.IntegerField(required=False, allow_null=True)
    diastolic_bp = serializers.IntegerField(required=False, allow_null=True)
    pulse_rate = serializers.IntegerField(required=False, allow_null=True)
    temperature = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True)
    spo2 = serializers.IntegerField(required=False, allow_null=True)
    respiratory_rate = serializers.IntegerField(required=False, allow_null=True)
    weight_kg = serializers.DecimalField(max_digits=5, decimal_places=1, required=False, allow_null=True)
    height_cm = serializers.DecimalField(max_digits=5, decimal_places=1, required=False, allow_null=True)
    bmi = serializers.DecimalField(max_digits=4, decimal_places=1, read_only=True)
    blood_sugar_rbs = serializers.IntegerField(required=False, allow_null=True)
    head_circumference_cm = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True)
    nurse_notes = serializers.CharField(required=False, allow_blank=True)


class AppointmentSerializer(serializers.ModelSerializer):
    vitals        = VitalsSerializer(read_only=True)
    has_encounter = serializers.SerializerMethodField()
    encounter     = serializers.SerializerMethodField()
    patient_name  = serializers.SerializerMethodField()
    patient_uhid  = serializers.SerializerMethodField()
    patient_age   = serializers.SerializerMethodField()
    patient_age_months = serializers.SerializerMethodField()
    patient_gender = serializers.SerializerMethodField()
    is_dependent  = serializers.SerializerMethodField()
    guardian_name = serializers.SerializerMethodField()
    guardian_relation = serializers.SerializerMethodField()
    patient_awpid = serializers.CharField(source="patient.awpid", read_only=True)
    awpid         = serializers.CharField(source="patient.awpid", read_only=True)
    doctor_name   = serializers.CharField(source="doctor.get_full_name", read_only=True)
    branch_id     = serializers.IntegerField(source="branch_department.branch_id", read_only=True)
    room_name     = serializers.SerializerMethodField()
    floor         = serializers.SerializerMethodField()
    visit_type    = serializers.CharField(source="appointment_type", read_only=True)
    department_name = serializers.CharField(source="branch_department.department.name", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id", "patient_id", "patient_awpid", "awpid",
            "patient_name", "patient_uhid", "patient_age", "patient_age_months", "patient_gender",
            "is_dependent", "guardian_name", "guardian_relation",
            "doctor_id", "doctor_name", "branch_id", "branch_department_id", "department_name",
            "appointment_type", "visit_type", "status",
            "scheduled_date", "scheduled_time",
            "token_number", "chief_complaint", "notes", "payment_preference",
            "room_id", "room_name", "floor",
            "started_at", "completed_at",
            "vitals", "has_encounter", "encounter", "created_at",
        ]
        read_only_fields = ["id", "token_number", "created_at"]

    def get_room_name(self, obj):
        return obj.room.name if obj.room_id else ""

    def get_floor(self, obj):
        return obj.room.floor.name if obj.room_id else ""

    def get_has_encounter(self, obj):
        return hasattr(obj, "a_encounter")

    def get_encounter(self, obj):
        try:
            enc = obj.a_encounter
            return {"id": str(enc.id), "status": enc.status}
        except Exception:
            return None

    def _get_patient(self, obj):
        return obj.patient

    def get_patient_name(self, obj):
        p = self._get_patient(obj)
        return p.get_patient_details()["full_name"] if p else ""

    def get_patient_uhid(self, obj):
        p = self._get_patient(obj)
        return p.uhid if p else ""

    def get_patient_age(self, obj):
        p = self._get_patient(obj)
        ym = _age_years_months(p.get_patient_details()["date_of_birth"]) if p else None
        return ym[0] if ym else None

    def get_patient_age_months(self, obj):
        p = self._get_patient(obj)
        ym = _age_years_months(p.get_patient_details()["date_of_birth"]) if p else None
        return ym[1] if ym else None

    def get_patient_gender(self, obj):
        p = self._get_patient(obj)
        return p.get_patient_details()["gender"] if p else ""

    def get_is_dependent(self, obj):
        p = self._get_patient(obj)
        return bool(p and p.get_patient_details()["is_dependent"])

    def get_guardian_name(self, obj):
        p = self._get_patient(obj)
        return p.get_patient_details()["guardian_name"] if p else ""

    def get_guardian_relation(self, obj):
        p = self._get_patient(obj)
        return p.get_patient_details()["guardian_relation"] if p else ""


class AppointmentCreateSerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField()
    doctor_id  = serializers.IntegerField()

    class Meta:
        model = Appointment
        fields = [
            "patient_id", "doctor_id",
            "appointment_type", "scheduled_date", "scheduled_time", "chief_complaint", "notes",
        ]

    def validate_appointment_type(self, value):
        hospital_db = self.context.get("hospital_db")
        if hospital_db and not OptionList.objects.using(hospital_db).filter(
            list_type=OptionList.LIST_APPOINTMENT_TYPE, value=value, is_active=True,
        ).exists():
            raise serializers.ValidationError("Not a configured appointment type for this hospital.")
        return value

    def validate(self, data):
        if not data.get("patient_id") or not data.get("doctor_id"):
            raise serializers.ValidationError("patient_id and doctor_id are required.")
        return data


class AppointmentTypeSerializer(serializers.ModelSerializer):
    """Generic read/write serializer for the appointment-type catalog."""
    name = serializers.CharField(source="label")

    class Meta:
        model  = OptionList
        fields = ["id", "name", "value", "is_active", "is_system", "sort_order"]
        read_only_fields = ["id", "value", "is_system"]


class AppointmentStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Appointment.STATUS_CHOICES)
    notes = serializers.CharField(required=False, allow_blank=True)


class PrescriptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionItem
        exclude = ["prescription"]
        read_only_fields = ["id"]


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True, read_only=True, source="rx_items")
    patient_id = serializers.IntegerField(source="encounter.appointment.patient_id", read_only=True)
    doctor_id = serializers.IntegerField(source="encounter.appointment.doctor_id", read_only=True)

    class Meta:
        model = Prescription
        fields = ["id", "rx_number", "encounter_id", "patient_id", "doctor_id",
                  "status", "notes", "items", "patient_choice", "payment_preference",
                  "payment_status", "invoice_id", "created_at", "updated_at"]
        read_only_fields = ["id", "rx_number", "created_at", "updated_at", "invoice_id"]


class OPDEncounterSerializer(serializers.ModelSerializer):
    prescription = PrescriptionSerializer(read_only=True, source="e_prescription")
    vitals       = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    patient_uhid = serializers.SerializerMethodField()
    patient_pk   = serializers.SerializerMethodField()
    patient_awpid = serializers.SerializerMethodField()
    doctor_name  = serializers.CharField(source="appointment.doctor.get_full_name", read_only=True)
    patient_id   = serializers.IntegerField(source="appointment.patient_id", read_only=True)
    doctor_id    = serializers.IntegerField(source="appointment.doctor_id", read_only=True)
    appointment_type = serializers.SerializerMethodField()
    patient_age  = serializers.SerializerMethodField()
    patient_age_months = serializers.SerializerMethodField()
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
            "id", "appointment_id", "patient_id", "doctor_id", "doctor_name",
            "patient_name", "patient_uhid", "patient_pk", "patient_awpid", "appointment_type", "patient_age", "patient_age_months", "patient_gender",
            "is_dependent", "guardian_name", "guardian_relation",
            "patient_last_visit", "encounter_date", "chief_complaint",
            "status", "subjective", "objective", "assessment", "plan",
            "investigations", "advice_to_patient", "follow_up_in_days",
            "followup_ask_nurse", "followup_nurse_note", "followup_nurse_requested_at",
            "followup_nurse_booked", "followup_nurse_booked_at",
            "diagnoses", "referred_to", "referral_notes",
            "signed_at", "prescription", "vitals", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "signed_at", "created_at", "updated_at"]

    def _patient(self, obj):
        return obj.appointment.patient

    def get_patient_name(self, obj):
        p = self._patient(obj)
        return p.get_patient_details()["full_name"] if p else ""

    def get_patient_uhid(self, obj):
        p = self._patient(obj)
        return p.uhid if p else ""

    def get_patient_pk(self, obj):
        p = self._patient(obj)
        return p.id if p else None

    def get_patient_awpid(self, obj):
        p = self._patient(obj)
        return p.awpid if p else None

    def get_appointment_type(self, obj):
        try:
            return obj.appointment.appointment_type
        except Exception:
            return ""

    def get_patient_age(self, obj):
        p = self._patient(obj)
        ym = _age_years_months(p.get_patient_details()["date_of_birth"]) if p else None
        return ym[0] if ym else None

    def get_patient_age_months(self, obj):
        p = self._patient(obj)
        ym = _age_years_months(p.get_patient_details()["date_of_birth"]) if p else None
        return ym[1] if ym else None

    def get_patient_gender(self, obj):
        p = self._patient(obj)
        return p.get_patient_details()["gender"] if p else ""

    def get_is_dependent(self, obj):
        p = self._patient(obj)
        return bool(p and p.get_patient_details()["is_dependent"])

    def get_guardian_name(self, obj):
        p = self._patient(obj)
        return p.get_patient_details()["guardian_name"] if p else ""

    def get_guardian_relation(self, obj):
        p = self._patient(obj)
        return p.get_patient_details()["guardian_relation"] if p else ""

    def get_patient_last_visit(self, obj):
        # Most recent OTHER completed visit for this patient at this hospital
        p = self._patient(obj)
        db = getattr(obj._state, "db", None) or self.context.get("db")
        if not p or not db:
            return None
        try:
            last = (Appointment.objects.using(db)
                    .filter(patient_id=p.id, status=Appointment.STATUS_DONE)
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
    appointment    = serializers.UUIDField(write_only=True, required=False)
    appointment_id = serializers.UUIDField(required=False)

    class Meta:
        model = OPDEncounter
        fields = [
            "appointment_id", "appointment",
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
            from apps.opd.vitals_service import record_vitals
            record_vitals(encounter.appointment, db, None, None, vitals_data)
        return encounter


class PrescriptionFavouriteSerializer(serializers.Serializer):
    """A doctor's saved prescription template: a name and the medicines (stored on the doctor's staff row)."""
    name = serializers.CharField(max_length=100)
    items = serializers.ListField(child=serializers.DictField(), default=list)


class FollowUpActionSerializer(serializers.Serializer):
    """POST body for FollowUpActionView. A doctor picks exactly one path per"""
    mode = serializers.ChoiceField(choices=["nurse", "reminder"])
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)
    follow_up_in_days = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs["mode"] == "reminder":
            days = attrs.get("follow_up_in_days")
            if not days or days < 1:
                raise serializers.ValidationError(
                    {"follow_up_in_days": "Enter at least 1 day out for a reminder."}
                )
        return attrs


class FollowupNurseWorklistItemSerializer(serializers.Serializer):
    """Read-only row shape for the nurse's 'Follow-ups to Book' worklist —"""
    encounter_id = serializers.CharField()
    patient_name = serializers.CharField()
    patient_uhid = serializers.CharField()
    doctor_name = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    requested_at = serializers.DateTimeField()
