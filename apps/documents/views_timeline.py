"""DRF API for the guardian app (React) and the clinician view."""
from datetime import date

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hospital_master.models import Hospital
from apps.hospital_patients.models import HospitalPatient
from apps.patients.models import Patient, RecurrenceFlag

from . import integration as ig
from .lib_documents import confirmed_q
from .lib_processing import SHOWN_VACCINES, build_timeline_payload, growth_dob, rebuild_patient
from .models import BirthHistory, ClinicalEvent, GrowthMeasurement, ImmunizationRecord, MedicalDocument
from .services.clinical_rules import age_in_months, classify_condition
from .services.config import load_config
from .services.config import GROWTH_REFERENCE_DIR
from .services.growth import INDICATORS, get_table, reference_curves
from .services.immunization import immunization_status, next_due, resolve_vaccines
from .tasks import rebuild_patient_task
from . import lib_clinical


# ------------------------------------------------------------------ helpers
def _patient_or_403(request, awpid):
    patient = get_object_or_404(Patient, awpid=awpid)
    if not ig.can_view_patient(request.user, patient):
        return None, Response({"detail": "Not allowed"}, status=status.HTTP_403_FORBIDDEN)
    return patient, None


def _clinician_or_403(request):
    if not ig.is_clinician(request.user):
        return Response({"detail": "Clinician access required"}, status=status.HTTP_403_FORBIDDEN)
    return None





def _first_of_each_reading(rows, column):
    """The same reading quoted by two reports is one point on the chart."""
    seen = set()
    for g in rows:
        key = (g.measured_on, getattr(g, column))
        if key not in seen:
            seen.add(key)
            yield g


def _reference_note(indicator, sex):
    """Names the reference tables that are really loaded: the files for children over 5 say what they are in older_children_source.txt (IAP 2015 when it is absent)."""
    if not get_table(INDICATORS[indicator], sex, "iap"):
        return "WHO 2006 (0-5 y)"
    named = GROWTH_REFERENCE_DIR / "older_children_source.txt"
    older = named.read_text(encoding="utf-8").strip() if named.exists() else "IAP 2015"
    if indicator == "weight_kg" and older.startswith("WHO 2007"):
        older += ", weight to 10 y"
    return f"WHO 2006 (0-5 y), {older} (5-18 y)"


def _staff_id(request):
    return request.user.pk if isinstance(request.user.pk, int) else None


def _parse_period(request, dob):
    if dob is None:                      # no date of birth on record: there is no timeline to draw
        return None, None
    try:
        p_to = date.fromisoformat(request.query_params.get("to")) if request.query_params.get("to") \
            else date.today()
        p_from = date.fromisoformat(request.query_params.get("from")) if request.query_params.get("from") \
            else dob
    except ValueError:
        return None, None
    return max(p_from, dob), p_to


# ----------------------------------------------------------------- timeline
class PatientHealthTimelineView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, awpid):
        patient, err = _patient_or_403(request, awpid)
        if err:
            return err
        dob, _ = ig.patient_dob_sex(patient)
        p_from, p_to = _parse_period(request, dob)
        if not p_from or p_from > p_to:
            return Response({"detail": "Invalid period"}, status=status.HTTP_400_BAD_REQUEST)
        audience = "doctor" if (request.query_params.get("view") == "doctor"
                                and ig.is_clinician(request.user)) else "guardian"
        return Response(build_timeline_payload(patient, p_from, p_to, audience, hospital_id=None))


def _medications_prescribed_here(request, patient):
    """The medicines the signed-in doctor's hospital prescribed to this patient, newest visit first. Each row opens the prescription document when
    one was filed for the visit."""
    from apps.opd.models import PrescriptionItem
    db = getattr(request, "hospital_db", None)
    if not db or db == "default":
        return []
    items = list(PrescriptionItem.objects.using(db)
                 .filter(prescription__encounter__appointment__patient__awpid=patient.awpid)
                 .select_related("prescription__encounter__appointment")
                 .order_by("-prescription__encounter__appointment__scheduled_date", "-prescription__created_at"))
    encounter_ids = {str(i.prescription.encounter_id) for i in items}
    documents = dict(MedicalDocument.objects.using("default")
                     .filter(patient=patient, source_type=MedicalDocument.Source.ENCOUNTER, source_id__in=encounter_ids,
                             doc_classification="prescription")
                     .values_list("source_id", "pk"))
    return [{"date": i.prescription.encounter.appointment.scheduled_date, "drug_name": i.drug_name, "dose": i.dosage, "unit": "",
             "frequency": i.frequency, "route": i.route, "duration_days": i.duration_days,
             "document_id": documents.get(i.prescription.encounter_id)} for i in items]


# ------------------------------------------------- doctor detail
class PatientClinicalSummaryView(APIView):
    """Doctors only: lab trends with reference ranges, the medicines this hospital prescribed, and what the timeline does not know."""
    permission_classes = (IsAuthenticated,)

    def get(self, request, awpid):
        patient, err = _patient_or_403(request, awpid)
        if err:
            return err
        err = _clinician_or_403(request)
        if err:
            return err
        hospital_id = None
        return Response({"labs": lib_clinical.lab_trends(patient, hospital_id), "medications": _medications_prescribed_here(request, patient),
                         "gaps": lib_clinical.data_gaps(patient, hospital_id)})


# ------------------------------------------------------------------- growth
class GrowthMeasurementIn(serializers.Serializer):
    measured_on = serializers.DateField()
    weight_kg = serializers.DecimalField(max_digits=6, decimal_places=3, required=False, allow_null=True)
    height_cm = serializers.DecimalField(max_digits=5, decimal_places=1, required=False, allow_null=True)
    head_circ_cm = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True)

    def validate(self, attrs):
        rng = load_config()["growth"]["plausible_ranges"]
        if not any(attrs.get(k) is not None for k in ("weight_kg", "height_cm", "head_circ_cm")):
            raise serializers.ValidationError("At least one measurement is required")
        for k in ("weight_kg", "height_cm", "head_circ_cm"):
            v = attrs.get(k)
            if v is not None and not (rng[k][0] <= float(v) <= rng[k][1]):
                raise serializers.ValidationError({k: f"Outside plausible range {rng[k]}"})
        if attrs["measured_on"] > date.today():
            raise serializers.ValidationError({"measured_on": "Cannot be in the future"})
        return attrs


class PatientGrowthView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, awpid):
        patient, err = _patient_or_403(request, awpid)
        if err:
            return err
        indicator = request.query_params.get("indicator", "weight_kg")
        if indicator not in INDICATORS:
            return Response({"detail": f"indicator must be one of {list(INDICATORS)}"}, status=400)
        dob, sex = ig.patient_dob_sex(patient)
        hospital_id = None
        own = {"source_hospital_id": hospital_id} if hospital_id is not None else {}
        bh = BirthHistory.objects.filter(confirmed_q(), patient=patient).first()
        corrected = growth_dob(dob, bh)
        age_now = age_in_months(dob, date.today())
        column = {"head_circ_cm": "head_circumference_cm"}.get(indicator, indicator)
        z_field, pct_field = {"weight_kg": ("weight_z", "weight_pct"),
                              "height_cm": ("height_z", "height_pct"),
                              "head_circ_cm": ("head_circ_z", "head_circ_pct")}[indicator]
        points = [{"date": g.measured_on.isoformat(), "age_months": round(age_in_months(corrected, g.measured_on), 2),
                   "value": float(getattr(g, column)), "z": getattr(g, z_field),
                   "percentile": getattr(g, pct_field), "flag": g.flags.get(column),
                   "document_id": g.document_id, "source": g.source}
                  for g in _first_of_each_reading(GrowthMeasurement.objects.filter(confirmed_q(), patient_id=patient.pk, is_rejected=False, **own)
                                                  .exclude(**{f"{column}__isnull": True}).order_by("measured_on", "pk"), column)]
        max_m = max([age_now + 3] + [p["age_months"] + 3 for p in points])
        max_m = min(max_m, 60 if indicator == "head_circ_cm" else 216)
        return Response({
            "indicator": indicator, "sex": sex,
            "uses_corrected_age": corrected != dob,
            "reference": reference_curves(INDICATORS[indicator], sex, max_m,
                                          step=0.5 if max_m <= 24 else 1.0),
            "reference_note": _reference_note(indicator, sex),
            "points": points,
        })

    def post(self, request, awpid):
        patient, err = _patient_or_403(request, awpid)
        if err:
            return err
        err = _clinician_or_403(request)
        if err:
            return err
        ser = GrowthMeasurementIn(data=request.data)
        ser.is_valid(raise_exception=True)
        values = dict(ser.validated_data)
        values["head_circumference_cm"] = values.pop("head_circ_cm", None)
        GrowthMeasurement.objects.create(patient_id=patient.pk, source="manual", **values)
        rebuild_patient(patient.pk)  # cheap; gives z-scores immediately
        return Response({"status": "created"}, status=status.HTTP_201_CREATED)


# ------------------------------------------------------------- immunization
class ImmunizationIn(serializers.Serializer):
    vaccine_text = serializers.CharField(max_length=100)
    given_on = serializers.DateField()

    def validate(self, attrs):
        if not resolve_vaccines(attrs["vaccine_text"]):
            raise serializers.ValidationError({"vaccine_text": "Vaccine not recognised"})
        if attrs["given_on"] > date.today():
            raise serializers.ValidationError({"given_on": "Cannot be in the future"})
        return attrs


class PatientImmunizationView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, awpid):
        patient, err = _patient_or_403(request, awpid)
        if err:
            return err
        dob, _ = ig.patient_dob_sex(patient)
        given = [{"vaccine_text": v.vaccine_name, "given_on": v.administered_date, "document_id": v.document_id,
                  "immunization_record_id": v.pk, "source": v.source}
                 for v in ImmunizationRecord.objects.filter(confirmed_q(), patient_id=patient.pk, verification_status__in=SHOWN_VACCINES,
                                                            administered_date__isnull=False)]
        st = immunization_status(dob, given, date.today())
        labels = load_config().get("patient_labels", {})
        for r in st["rows"]:
            r["status_label"] = labels.get(r["status"], r["status"])
        st["next_due"] = next_due(st)
        return Response(st)

    def post(self, request, awpid):
        patient, err = _patient_or_403(request, awpid)
        if err:
            return err
        ser = ImmunizationIn(data=request.data)
        ser.is_valid(raise_exception=True)
        ImmunizationRecord.objects.create(
            patient_id=patient.pk, source=ImmunizationRecord.SOURCE_MANUAL,
            verification_status=ImmunizationRecord.STATUS_VERIFIED if ig.is_clinician(request.user) else ImmunizationRecord.STATUS_PENDING,
            vaccines=resolve_vaccines(ser.validated_data["vaccine_text"]), vaccine_name=ser.validated_data["vaccine_text"],
            administered_date=ser.validated_data["given_on"])
        return Response({"status": "created"}, status=status.HTTP_201_CREATED)


# ------------------------------------------------------------ clinician ops
class ClinicalEventPatch(serializers.Serializer):
    action = serializers.ChoiceField(choices=["verify", "reject", "recode"])
    icd10 = serializers.CharField(max_length=10, required=False)
    condition_text = serializers.CharField(max_length=255, required=False)
    is_provisional = serializers.BooleanField(required=False)


class ClinicalEventView(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, event_id):
        err = _clinician_or_403(request)
        if err:
            return err
        ev = get_object_or_404(ClinicalEvent, pk=event_id)
        patient, err = _patient_or_403(request, ev.patient.awpid)
        if err:
            return err
        ser = ClinicalEventPatch(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        if d["action"] == "reject":
            ev.verification_status = "rejected"
        else:
            if d["action"] == "recode":
                if "icd10" in d:
                    ev.icd10 = d["icd10"].upper()
                    cls = classify_condition(ev.icd10)
                    ev.condition_group, ev.category = cls["group"], cls["category"]
                if "condition_text" in d:
                    ev.condition_text = d["condition_text"]
            if "is_provisional" in d:
                ev.is_provisional = d["is_provisional"]
            ev.verification_status = "verified"
        ev.verified_at = timezone.now()
        ev.save()
        rebuild_patient_task.delay(ev.patient_id)
        return Response({"status": "ok", "event_id": ev.pk})


class RecurrenceAckView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, flag_id):
        err = _clinician_or_403(request)
        if err:
            return err
        flag = get_object_or_404(RecurrenceFlag, pk=flag_id)
        _, err = _patient_or_403(request, flag.patient.awpid)
        if err:
            return err
        flag.acknowledged_by_id, flag.acknowledged_at = _staff_id(request), timezone.now()
        flag.save(update_fields=["acknowledged_by_id", "acknowledged_at", "updated_at"])
        return Response({"status": "ok"})


class PatientRebuildView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, awpid):
        err = _clinician_or_403(request)
        if err:
            return err
        patient, err = _patient_or_403(request, awpid)
        if err:
            return err
        rebuild_patient_task.delay(patient.pk)
        return Response({"status": "queued"}, status=status.HTTP_202_ACCEPTED)
