"""
apps/patients/records_share_views.py
------------------------------------
"Records Access" — the doctor-has-a-laptop half of break-glass record
sharing (see registry.RecordsShareRequest for the model-level design).

Contrast with the older "Emergency QR" flow (emergency_views.py): that one
is stateless — the *patient's* phone shows a signed-JWT QR and any camera
opens a read-only page. This one is the inverse and stateful:

    doctor's laptop opens /records-access  ─▶  a pending row is created here,
    a QR + short code are shown             ─▶  patient scans, sees who is
    asking, approves on their phone         ─▶  a 2-hour window opens and the
    laptop (polling the token) renders the patient's navigable history +
    Rx & Reports vault, read-only. Downloads are released one file at a time.

Public endpoints (AllowAny) are gated only by the 32-char random `token`
(and, for anything that returns data, by the row being an approved-and-
unexpired grant). The decision / end / download-approval endpoints are
patient-authenticated (IsPatient) and additionally check the grant's awpid
matches the caller.

Registry DB only — no tenant fan-out — exactly like emergency_views.py, and
for the same reasons (this is reachable by someone with no account here).
"""

import hashlib
import logging
import secrets

from django.utils import timezone
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from core.response import success, error
from core.permissions import IsPatient
from core import storage as blob_storage
from apps.registry.models import (
    PatientIdentity, PatientAccount,
    SharedDocument, SharedVaccination,
    EmergencyAccessLog, RecordsShareRequest, RecordsPrivacy,
)
from apps.patients.portal_views import EMERGENCY_SHARE_CATEGORIES, _render_qr_data_uri

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────── helpers

def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")


# Pairing codes avoid 0/O/1/I so they read cleanly off a screen and back into
# a phone.
_PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _make_pairing(n=6):
    return "".join(secrets.choice(_PAIRING_ALPHABET) for _ in range(n))


def _device_token(request):
    return request.META.get("HTTP_X_SHARE_DEVICE", "").strip()


def _device_guard(grant, request):
    """
    Once a laptop has claimed this session, every public read must come from
    that same browser (it holds the device token from the claim response).
    Returns an error Response to bail with, or None to proceed. A leaked link
    or a photographed QR carries no device token, so it reads nothing.
    """
    if grant.opened_at and not grant.device_matches(_device_token(request)):
        from django.conf import settings
        host = settings.FRONTEND_URL.rstrip("/").split("://", 1)[-1]
        return error(
            f"Open this from the code the patient gave you at "
            f"{host}/share — this link is tied to the computer "
            f"that started the session.",
            errors={"reason": "device_mismatch"}, status=403,
        )
    return None


def _get_grant(token):
    """
    Fetch a RecordsShareRequest by its token, or — when the patient typed the
    6-digit pairing code into the app instead of scanning — by that code
    (newest still-pending one wins; codes are only unique among live requests).
    Lapses an expired grant before returning it.
    """
    grant = RecordsShareRequest.objects.using("default").filter(token=token).first()
    if not grant and token and token.isdigit() and len(token) == 6:
        grant = (
            RecordsShareRequest.objects.using("default")
            .filter(code=token, status=RecordsShareRequest.STATUS_PENDING)
            .order_by("-created_at")
            .first()
        )
    if grant:
        grant.lapse_if_due()
    return grant


def _audit(awpid, event, ip=None):
    try:
        EmergencyAccessLog.objects.using("default").create(
            awpid=awpid or "", event=event, ip_address=ip,
        )
    except Exception:
        logger.exception("EmergencyAccessLog write failed (%s) for awpid=%s", event, awpid)


def _self_awpid(request):
    acct = PatientAccount.objects.using("default").filter(pk=request.user.id).first()
    return acct.awpid if acct else None


def _patient_name(awpid):
    """Identity is the source of truth, but a self-registered patient may only
    have a PatientAccount — fall back to it before giving up."""
    identity = PatientIdentity.objects.using("default").filter(awpid=awpid).first()
    if identity and identity.full_name:
        return identity.full_name, identity
    acct = PatientAccount.objects.using("default").filter(awpid=awpid).first()
    return (acct.full_name if acct else ""), identity


# The navigable Rx & Reports vault — same row shape PortalDocumentListCreateView
# returns, so the frontend list/detail components are reused unchanged. The
# consult-pad handwritten prescription is folded into its typeset sibling as
# `handwritten_doc_id` rather than showing as its own row.
def _vault_documents(awpid, limit=200):
    hw_rows = list(
        SharedDocument.objects.using("default")
        .filter(awpid=awpid, source_ref__endswith=":handwritten:rx")
        .values_list("id", "source_ref")
    )
    base_refs = set(
        SharedDocument.objects.using("default")
        .filter(awpid=awpid, source_ref__startswith="encounter:")
        .exclude(source_ref__contains=":handwritten:")
        .values_list("source_ref", flat=True)
    )
    hw_by_base, linked_hw_ids = {}, []
    for hid, ref in hw_rows:
        base = ref.rsplit(":handwritten:rx", 1)[0]
        if base in base_refs:
            hw_by_base[base] = hid
            linked_hw_ids.append(hid)

    rows = (
        SharedDocument.objects.using("default")
        .filter(awpid=awpid, hidden_at__isnull=True, deleted_at__isnull=True)
        .exclude(doc_type__in=SharedDocument.STAFF_ONLY_DOC_TYPES)
        .exclude(id__in=linked_hw_ids)
        .exclude(review_state="unsorted")
        .exclude(verification_status="needs_review")
        .order_by("-created_at")[:limit]
    )
    return [{
        "id":                d.id,
        "title":             d.title,
        "doc_type":          d.doc_type,
        "file_name":         d.file_name,
        "mime_type":         d.mime_type,
        "uploaded_by":       d.uploaded_by,
        "created_at":        d.created_at,
        "review_state":      d.review_state,
        "verification_status": d.verification_status,
        "document_date":     d.document_date,
        "collection_date":   d.collection_date,
        "report_categories": d.report_categories or [],
        "public_document_id": d.public_document_id,
        "hospital_label":    d.hospital_label,
        "doctor_label":      d.doctor_label,
        "source_tenant_id":  d.source_tenant_id,
        "handwritten_doc_id": hw_by_base.get(d.source_ref),
    } for d in rows]


# ─────────────────────────────────────────────────────────── privacy layer
#
# The patient's standing "what a doctor sees" choices (registry.RecordsPrivacy)
# subtract from the vault before it reaches a share session. A record hidden
# here stays hidden in every future share; the only way one reaches a doctor
# is a per-visit reveal that the patient makes on the live grant
# (RecordsShareRequest.shown_private_ids), which is dropped when the visit ends.

def _privacy_for(awpid):
    return RecordsPrivacy.objects.using("default").filter(awpid=awpid).first()


def _privacy_hidden_ids(awpid, docs, privacy=None):
    """
    docs = the dicts returned by _vault_documents(awpid). Returns the set of
    SharedDocument ids the patient's standing privacy hides from a doctor —
    the union of hide_all, the live category / kind rules, and individually
    locked ids. Per-visit reveals are added back by the caller.
    """
    p = privacy if privacy is not None else _privacy_for(awpid)
    if not p:
        return set()
    if p.hide_all:
        return {d["id"] for d in docs}
    cats = set(p.hidden_categories or [])
    kinds = set(p.hidden_kinds or [])
    hidden = set(p.hidden_doc_ids or [])
    for d in docs:
        if d["id"] in hidden:
            continue
        if d["doc_type"] in kinds:
            hidden.add(d["id"])
        elif cats and (set(d.get("report_categories") or []) & cats):
            hidden.add(d["id"])
    return hidden


_SECTION_LABELS = {
    "summary":      "Summary",
    "vitals":       "Recent vitals",
    "diagnoses":    "Diagnoses & clinical notes",
    "vaccinations": "Vaccinations",
}


def _pending_download_payload(grant):
    if not grant.pending_download_id:
        return None
    doc = SharedDocument.objects.using("default").filter(
        id=grant.pending_download_id, awpid=grant.awpid,
    ).first()
    return {
        "id": grant.pending_download_id,
        "title": doc.title if doc else "a document",
    }


# ─────────────────────────────────────────────────────────────── patient: create

class RecordsShareCreateView(APIView):
    """
    POST /api/v1/portal/records-share/

    The PATIENT starts the flow from their app: this mints a pending session
    bound to their awpid and returns a link to hand to the doctor. The doctor
    opens that link on a laptop (no account), the laptop shows a QR, the
    patient scans it and confirms — only then does the session go live.

    Body (optional): { "note": "Dr. Rao" }  — a label the patient can attach
    so their "who has access" list is readable later.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)

        note = (request.data.get("note") or request.data.get("requester_label") or "").strip()[:120]

        token = secrets.token_hex(16)                    # 32 hex chars
        code = f"{secrets.randbelow(1_000_000):06d}"     # spoken fallback

        grant = RecordsShareRequest.objects.using("default").create(
            token=token, code=code, requester_label=note, awpid=me,
            status=RecordsShareRequest.STATUS_PENDING, created_ip=_client_ip(request),
        )

        from django.conf import settings
        link = f"{settings.FRONTEND_URL.rstrip('/')}/share-records/{token}"

        return success(data={
            "token": grant.token,
            "code": grant.code,
            "link": link,
            "status": grant.status,
            "window_hours": RecordsShareRequest.WINDOW_HOURS,
        }, status=201)


# ─────────────────────────────────────────────────────────────── doctor / public


class RecordsShareClaimView(APIView):
    """
    POST /api/v1/records-share/claim/
      body: { "code": "482193" }   — the doctor types the patient's 6 digits
                                      at clinic.atomwalk.com/share
        or: { "token": "<32 hex>" } — the doctor opened a full share link and
                                      the page is binding itself

    Ties this session to the calling browser: mints a random device token
    (returned once, kept by that browser and sent as X-Share-Device on every
    later read) and a 6-char `pairing` shown on the doctor's screen for the
    patient to scan/type when approving. Only works while the session is still
    pending — a link that leaks after approval cannot claim its way in.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def post(self, request):
        raw = (request.data.get("code") or request.data.get("token") or "").strip()
        by_code = raw.isdigit() and len(raw) == 6

        if by_code:
            grant = (
                RecordsShareRequest.objects.using("default")
                .filter(code=raw, status=RecordsShareRequest.STATUS_PENDING)
                .order_by("-created_at")
                .first()
            )
        else:
            grant = RecordsShareRequest.objects.using("default").filter(token=raw).first()

        if not grant or (by_code and grant.pending_stale):
            return error("That code didn't match a waiting request. Ask the "
                         "patient to create a new share and read you the code.",
                         status=404)
        grant.lapse_if_due()

        if grant.status == RecordsShareRequest.STATUS_APPROVED:
            return error("This session is already open on another computer. Ask "
                         "the patient to share again if you need a fresh one.",
                         errors={"status": grant.status}, status=409)
        if grant.status != RecordsShareRequest.STATUS_PENDING:
            return error("This request has ended. Ask the patient for a new code.",
                         errors={"status": grant.status}, status=409)

        device = secrets.token_hex(16)
        grant.device_hash = hashlib.sha256(device.encode()).hexdigest()
        grant.pairing = _make_pairing()
        grant.opened_at = grant.opened_at or timezone.now()
        grant.save(using="default", update_fields=[
            "device_hash", "pairing", "opened_at",
        ])

        return success(data={
            "token": grant.token,
            "device_token": device,
            "pairing": grant.pairing,
            "requester_label": grant.requester_label,
            "window_hours": RecordsShareRequest.WINDOW_HOURS,
            "status": grant.status,
        }, status=201)


class RecordsShareStatusView(APIView):
    """
    GET /api/v1/records-share/<token>/

    Polled by the doctor's laptop while it waits, and also read by the
    patient's phone right after a scan to show "who is asking" before they
    decide. Returns identifying patient data only once the grant is a live
    approval.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def get(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)

        bail = _device_guard(grant, request)
        if bail:
            return bail

        # Heartbeat so the patient's "who has access" view can show whether
        # the doctor is actively looking right now.
        if grant.is_live:
            RecordsShareRequest.objects.using("default").filter(pk=grant.pk).update(
                last_seen_at=timezone.now())

        data = {
            "token": grant.token,
            "status": grant.status,
            "pairing": grant.pairing,
            "requester_label": grant.requester_label,
            "window_hours": RecordsShareRequest.WINDOW_HOURS,
            "seconds_left": grant.seconds_left() if grant.is_live else 0,
        }
        if grant.status == RecordsShareRequest.STATUS_PENDING:
            from django.conf import settings
            link = f"{settings.FRONTEND_URL.rstrip('/')}/share-records/{grant.token}"
            if grant.pairing:
                link = f"{link}?p={grant.pairing}"
            data["qr_image"] = _render_qr_data_uri(link)
        if grant.is_live:
            data["patient_name"] = _patient_name(grant.awpid)[0]
            data["pending_download"] = _pending_download_payload(grant)
        return success(data=data)


class RecordsShareRecordsView(APIView):
    """
    GET /api/v1/records-share/<token>/records/

    The read-only payload the laptop renders once approved: patient header,
    shared clinical history (allergies / diagnoses / vitals / prescriptions),
    and the navigable Rx & Reports vault. File contents are NOT included —
    every document is "locked" until the patient releases it for download
    (see RecordsShareDownloadView).
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def get(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)
        bail = _device_guard(grant, request)
        if bail:
            return bail
        if not grant.is_live:
            return error(
                "This access has ended. Ask the patient to grant access again.",
                errors={"status": grant.status}, status=403,
            )

        from apps.patients.services import PatientService
        from apps.patients.emergency_views import _resolve_emergency_contact, _vaccination_history
        name, identity = _patient_name(grant.awpid)
        history = PatientService.get_shared_history(awpid=grant.awpid)

        unlocked = set(grant.download_unlocked_ids or [])
        documents = _vault_documents(grant.awpid)

        # ── standing privacy: drop what the patient keeps private, minus the
        #    records they revealed for this one visit ──────────────────────
        privacy = _privacy_for(grant.awpid)
        hidden_ids = _privacy_hidden_ids(grant.awpid, documents, privacy)
        shown_now = set(grant.shown_private_ids or [])
        withheld = sum(1 for d in documents if d["id"] in hidden_ids and d["id"] not in shown_now)
        documents = [d for d in documents if d["id"] not in hidden_ids or d["id"] in shown_now]
        hidden_sections = list((privacy.hidden_sections if privacy else []) or [])

        for d in documents:
            d["revealed_for_visit"] = d["id"] in hidden_ids and d["id"] in shown_now
            d["download_state"] = (
                "unlocked" if d["id"] in unlocked
                else "requested" if d["id"] == grant.pending_download_id
                else "locked"
            )

        def _age(dob):
            if not dob:
                return None
            t = timezone.localdate()
            return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))

        # Current meds = the drugs on the most recent prescription.
        current_meds = []
        if history["prescriptions"]:
            for it in (history["prescriptions"][0].get("items") or []):
                bits = [it.get("drug_name"), it.get("dose"), it.get("frequency")]
                current_meds.append(" ".join(b for b in bits if b))

        _audit(grant.awpid, EmergencyAccessLog.EVENT_VIEWED, _client_ip(request))

        summary = {
            "current_meds": [] if "summary" in hidden_sections else current_meds,
            "emergency_contact": None if "summary" in hidden_sections
                                 else _resolve_emergency_contact(grant.awpid),
        }
        sections_withheld = [
            _SECTION_LABELS[s] for s in RecordsPrivacy.SECTIONS if s in hidden_sections
        ]

        return success(data={
            "patient": {
                "full_name": name,
                "awpid": grant.awpid,
                "age_years": _age(identity.date_of_birth) if identity else None,
                "gender": identity.gender if identity else "",
                "blood_group": identity.blood_group if identity else "",
            },
            "summary": summary,
            "allergies": history["allergies"],
            "diagnoses": [] if "diagnoses" in hidden_sections else history["diagnoses"],
            "vitals": [] if "vitals" in hidden_sections else history["vitals"],
            "prescriptions": history["prescriptions"],
            "vaccinations": [] if "vaccinations" in hidden_sections
                            else _vaccination_history(grant.awpid),
            "documents": documents,
            # One honest line for the clinician: the record list / sections may
            # be partial. It never says *what* is held back.
            "records_withheld": withheld > 0,
            "sections_withheld": sections_withheld,
            "requester_label": grant.requester_label,
            "seconds_left": grant.seconds_left(),
            "window_hours": RecordsShareRequest.WINDOW_HOURS,
        })


class RecordsShareDownloadView(APIView):
    """
    POST /api/v1/records-share/<token>/downloads/   body: { "doc_id": 123 }

    If the patient has already released this document, returns a signed URL.
    Otherwise records it as the pending download request — the patient sees
    it on their phone and allows or denies (RecordsShareDownloadDecisionView).
    Only one pending request at a time; a new one replaces the last.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def post(self, request, token):
        grant = _get_grant(token)
        bail = grant and _device_guard(grant, request)
        if bail:
            return bail
        if not grant or not grant.is_live:
            return error("This access has ended.", status=403)

        try:
            doc_id = int(request.data.get("doc_id"))
        except (TypeError, ValueError):
            return error("Which document?", errors={"doc_id": "Required."})

        doc = SharedDocument.objects.using("default").filter(
            id=doc_id, awpid=grant.awpid, hidden_at__isnull=True, deleted_at__isnull=True,
        ).first()
        if not doc:
            return error("That document isn't part of this patient's records.", status=404)

        if doc_id in (grant.download_unlocked_ids or []):
            return success(data={"state": "unlocked", "file_url": blob_storage.signed_url(doc.file_data)})

        RecordsShareRequest.objects.using("default").filter(pk=grant.pk).update(
            pending_download_id=doc_id)
        return success(data={"state": "requested"})


class RecordsShareDocumentViewView(APIView):
    """
    GET /api/v1/records-share/<token>/documents/<doc_id>/view/

    Open a document in the browser — instant, no patient approval. The
    patient already granted the whole session; *saving a copy* is the extra
    step, not looking at one (see RecordsShareDownloadView for that).

    That separation only holds if "view" never hands over anything a
    one-click browser action can turn into a saved file. A raw signed PDF
    URL opened in a new tab renders in the browser's own PDF viewer, which
    carries its own Download/Print buttons — a doctor could bypass the
    per-file patient-approval gate entirely just by using those, with no
    audit trail. So for a PDF, this rasterises each page to a PNG
    server-side (same renderer core.ocr uses for OCR) and returns those
    instead of a URL — a page rendered as an <img> in our own page carries
    no native viewer chrome to download or print from. For an image
    document there's no separate "native viewer" risk (the frontend fetches
    it into an <img> itself rather than navigating to the raw URL), so the
    signed URL is still returned directly.

    This doesn't make a screenshot impossible — nothing served to a browser
    ever can. It removes the specific, no-friction, easy-to-stumble-on
    Download icon that made bypassing the consent gate no different from
    just looking.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def get(self, request, token, doc_id):
        grant = _get_grant(token)
        bail = grant and _device_guard(grant, request)
        if bail:
            return bail
        if not grant or not grant.is_live:
            return error("This access has ended.", status=403)
        doc = SharedDocument.objects.using("default").filter(
            id=doc_id, awpid=grant.awpid, hidden_at__isnull=True, deleted_at__isnull=True,
        ).first()
        if not doc:
            return error("That document isn't part of this patient's records.", status=404)

        if doc.mime_type == "application/pdf":
            import base64
            from core import ocr as _ocr

            raw = doc.file_data or ""
            if raw.startswith("data:"):
                file_bytes = base64.b64decode(raw.split(",", 1)[1])
            else:
                file_bytes = blob_storage.get_bytes(raw)
            pages = _ocr.pdf_page_images(file_bytes, max_pages=12, dpi=150)
            if not pages:
                return error("Couldn't render this document for viewing.", status=500)
            return success(data={
                "mime_type": "application/pdf",
                "pages": [f"data:image/png;base64,{base64.b64encode(p).decode()}" for p in pages],
            })

        return success(data={"mime_type": doc.mime_type, "file_url": blob_storage.signed_url(doc.file_data)})


class RecordsShareCloseView(APIView):
    """
    POST /api/v1/records-share/<token>/close/

    The doctor closing the session from their laptop. Ending access early is
    always safe and the token holder is the doctor, so no auth — unlike the
    patient's /end/ which is inside the portal.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def post(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)
        bail = _device_guard(grant, request)
        if bail:
            return bail
        if grant.status in (RecordsShareRequest.STATUS_APPROVED, RecordsShareRequest.STATUS_PENDING):
            grant.status = RecordsShareRequest.STATUS_ENDED
            grant.pending_download_id = None
            grant.shown_private_ids = []
            grant.save(using="default", update_fields=["status", "pending_download_id", "shown_private_ids"])
        return success(data={"status": grant.status}, message="Access ended.")


# ─────────────────────────────────────────────────────────────── patient (auth)

class RecordsShareDecisionView(APIView):
    """
    POST /api/v1/records-share/<token>/decision/
      body: { "approve": true, "pairing": "K7M2QP", "consent_confirmed": true }

    Called by the patient after they scan the QR on the doctor's screen. That
    QR carries the session's `pairing` (…/share-records/<token>?p=K7M2QP); the
    app lifts it out and sends it here — or, if the camera won't cooperate,
    the patient reads the 6 characters shown under the QR and types them. It
    proves the patient is looking at the doctor's live screen, not replaying a
    copied link. Too many wrong tries locks the session. `approve:false`
    declines it. The right pairing but no `consent_confirmed` returns 428 with
    the list of what will be shared. The session was created by this same
    patient, so its awpid must match the caller.
    """
    permission_classes = [IsPatient]

    def post(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)
        if grant.status != RecordsShareRequest.STATUS_PENDING:
            return error("This request has already been answered.",
                         errors={"status": grant.status}, status=409)

        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)
        if grant.awpid and grant.awpid != me:
            return error("This share link was created by a different account.", status=403)

        approve = bool(request.data.get("approve"))

        if not approve:
            grant.status = RecordsShareRequest.STATUS_DENIED
            grant.decided_at = timezone.now()
            grant.awpid = me
            grant.save(using="default", update_fields=["status", "decided_at", "awpid"])
            _audit(me, EmergencyAccessLog.EVENT_GENERATED, _client_ip(request))
            return success(data={"status": grant.status}, message="Request declined.")

        # ── pairing check — the patient lifts it off the doctor's screen ───
        if not grant.opened_at or not grant.pairing:
            return error(
                "Ask the doctor to open the link on their computer first — a "
                "code will appear on their screen for you to scan.",
                errors={"reason": "not_opened"}, status=409,
            )
        submitted = "".join(
            ch for ch in str(request.data.get("pairing") or "").upper()
            if ch in _PAIRING_ALPHABET
        )
        if submitted != grant.pairing:
            grant.code_attempts += 1
            fields = ["code_attempts"]
            locked = grant.code_attempts >= RecordsShareRequest.MAX_CODE_ATTEMPTS
            if locked:
                grant.status = RecordsShareRequest.STATUS_DENIED
                grant.decided_at = timezone.now()
                grant.awpid = me
                fields += ["status", "decided_at", "awpid"]
            grant.save(using="default", update_fields=fields)
            if locked:
                return error(
                    "Too many wrong tries — this link is now locked. Ask the doctor to open a new one.",
                    errors={"status": grant.status}, status=423,
                )
            return error(
                "That doesn't match the code on the doctor's screen. Check it and try again.",
                errors={"attempts_left": RecordsShareRequest.MAX_CODE_ATTEMPTS - grant.code_attempts},
                status=400,
            )

        if not request.data.get("consent_confirmed"):
            return error(
                "Confirm what you're sharing before granting access.",
                errors={
                    "consent_required": True,
                    "share_categories": EMERGENCY_SHARE_CATEGORIES,
                    "window_hours": RecordsShareRequest.WINDOW_HOURS,
                },
                status=428,
            )

        now = timezone.now()
        grant.awpid = me
        grant.status = RecordsShareRequest.STATUS_APPROVED
        grant.decided_at = now
        grant.expires_at = now + timedelta(hours=RecordsShareRequest.WINDOW_HOURS)
        grant.save(using="default", update_fields=["awpid", "status", "decided_at", "expires_at"])
        _audit(me, EmergencyAccessLog.EVENT_GENERATED, _client_ip(request))

        return success(data={
            "token": grant.token,
            "status": grant.status,
            "requester_label": grant.requester_label,
            "expires_at": grant.expires_at,
            "seconds_left": grant.seconds_left(),
        }, message="Access granted for the next 2 hours.")


class RecordsShareEndView(APIView):
    """POST /api/v1/records-share/<token>/end/ — patient ends a live grant early."""
    permission_classes = [IsPatient]

    def post(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)

        me = _self_awpid(request)
        if grant.awpid and grant.awpid != me:
            return error("This isn't your access grant.", status=403)
        if grant.status not in (RecordsShareRequest.STATUS_APPROVED, RecordsShareRequest.STATUS_PENDING):
            return success(data={"status": grant.status})

        grant.status = RecordsShareRequest.STATUS_ENDED
        grant.pending_download_id = None
        grant.shown_private_ids = []
        grant.save(using="default", update_fields=["status", "pending_download_id", "shown_private_ids"])
        return success(data={"status": grant.status}, message="Access ended.")


class RecordsShareDownloadDecisionView(APIView):
    """
    POST /api/v1/records-share/<token>/downloads/decision/  body: { "approve": true }

    The patient allows or denies the doctor's pending download request. On
    allow, that document id moves into `download_unlocked_ids` and stays
    downloadable for the rest of the window.
    """
    permission_classes = [IsPatient]

    def post(self, request, token):
        grant = _get_grant(token)
        if not grant or not grant.is_live:
            return error("This access has ended.", status=403)

        me = _self_awpid(request)
        if grant.awpid != me:
            return error("This isn't your access grant.", status=403)
        if not grant.pending_download_id:
            return success(data={"pending_download": None})

        doc_id = grant.pending_download_id
        fields = ["pending_download_id"]
        if bool(request.data.get("approve")):
            unlocked = list(grant.download_unlocked_ids or [])
            if doc_id not in unlocked:
                unlocked.append(doc_id)
            grant.download_unlocked_ids = unlocked
            fields.append("download_unlocked_ids")
        grant.pending_download_id = None
        grant.save(using="default", update_fields=fields)
        return success(data={"pending_download": None, "unlocked_ids": grant.download_unlocked_ids})


class RecordsShareMineView(APIView):
    """
    GET /api/v1/records-share/mine/

    The patient's "who currently has access to my records" surface — every
    live grant they've approved, with any pending download request. The
    mobile app polls this to show the break-glass banner + approval prompts.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)

        grants = (
            RecordsShareRequest.objects.using("default")
            .filter(awpid=me, status=RecordsShareRequest.STATUS_APPROVED)
            .order_by("-decided_at")
        )
        out = []
        for g in grants:
            if g.lapse_if_due():
                continue
            out.append({
                "token": g.token,
                "requester_label": g.requester_label,
                "approved_at": g.decided_at,
                "expires_at": g.expires_at,
                "seconds_left": g.seconds_left(),
                "last_seen_at": g.last_seen_at,
                "pending_download": _pending_download_payload(g),
            })
        return success(data={"grants": out})


# ─────────────────────────────────────────────── patient: standing privacy
#
# The dedicated privacy screen shows the whole vault, grouped by lab-report
# panel (CBC / Lipid / Thyroid …) with the uncategorised kinds after. It can
# run to hundreds of rows, so the list is paged — but the screen's headline
# numbers (the "shown / total" readout, Hide-all / Show-all, the per-category
# facet counts) all speak for the *whole* vault, so those travel in `summary`
# while `documents` carries just one page. Pages break on category
# boundaries: a group is never split across pages, and a group larger than
# the soft row target sits alone on its own page, so every group pill the
# client renders is accurate for what's on screen.

from collections import Counter
from core.report_types import SLUGS as _PANEL_SLUGS, label_for as _panel_label

_PANEL_RANK = {s: i for i, s in enumerate(_PANEL_SLUGS)}
_KIND_ORDER = ["lab_report", "prescription", "scan", "discharge_summary", "other"]
_KIND_LABEL = {
    "lab_report": "Lab reports", "prescription": "Prescriptions", "scan": "Imaging",
    "discharge_summary": "Discharge summaries", "other": "Documents",
}
_PRIVACY_VAULT_MAX = 1000          # one patient's manageable ceiling
_PRIVACY_PAGE_ROWS = 40           # soft per-page target; whole groups, never split
_PRIVACY_PAGE_MAX = 200


def _row_date_key(d):
    v = d.get("document_date") or d.get("created_at")
    return v.isoformat() if hasattr(v, "isoformat") else (v or "")


def _bucket_of(row):
    """(key, label, rank) — the one panel/kind bucket a row is grouped under."""
    cats = [c for c in (row.get("report_categories") or []) if c in _PANEL_RANK]
    if cats:
        first = min(cats, key=lambda c: _PANEL_RANK[c])
        return f"c:{first}", _panel_label(first), _PANEL_RANK[first]
    k = row.get("doc_type") or "other"
    rank = 100 + (_KIND_ORDER.index(k) if k in _KIND_ORDER else 99)
    return f"k:{k}", _KIND_LABEL.get(k, "Documents"), rank


def _bucket_groups(rows):
    groups = {}
    for r in rows:
        key, label, rank = _bucket_of(r)
        g = groups.get(key)
        if not g:
            g = groups[key] = {"key": key, "label": label, "rank": rank, "list": []}
        g["list"].append(r)
    ordered = sorted(groups.values(), key=lambda g: g["rank"])
    for g in ordered:
        g["list"].sort(key=_row_date_key, reverse=True)
    return ordered


def _paginate_groups(groups, page, target=_PRIVACY_PAGE_ROWS):
    """Pack ordered groups into pages of ~`target` rows without splitting a
    group; an oversize group takes a page to itself. Returns (rows, meta)."""
    pages, cur, cur_n = [], [], 0
    for g in groups:
        gn = len(g["list"])
        if cur and cur_n + gn > target:
            pages.append(cur); cur, cur_n = [], 0
        cur.append(g); cur_n += gn
        if cur_n >= target:
            pages.append(cur); cur, cur_n = [], 0
    if cur:
        pages.append(cur)
    total_pages = max(1, len(pages))
    page = min(max(page, 1), total_pages)
    sel = pages[page - 1] if pages else []
    rows = [d for g in sel for d in g["list"]]
    return rows, {
        "page": page,
        "page_size": target,
        "total_pages": total_pages,
        "total_count": sum(len(g["list"]) for g in groups),
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }


class RecordsPrivacyView(APIView):
    """
    GET  /api/v1/portal/records-privacy/
    PUT  /api/v1/portal/records-privacy/

    The patient's standing "what a doctor sees when I share my records"
    config, plus the full vault annotated with each row's effective private
    state (for the dedicated privacy screen). GET also reports whether a
    share session is live right now — the frontend asks "just this visit or
    always?" only then, otherwise a plain confirm.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)

        p = RecordsPrivacy.for_awpid(me)
        docs = _vault_documents(me, limit=_PRIVACY_VAULT_MAX)
        hidden = _privacy_hidden_ids(me, docs, p)
        locked_ids = set(p.hidden_doc_ids or [])

        live = (
            RecordsShareRequest.objects.using("default")
            .filter(awpid=me, status=RecordsShareRequest.STATUS_APPROVED)
            .order_by("-decided_at")
            .first()
        )
        if live and not live.is_live:
            live = None
        shown_now = set(live.shown_private_ids or []) if live else set()

        # ── annotate the whole (capped) vault once ───────────────────────────
        rows = [{
            "id":                d["id"],
            "title":             d["title"],
            "doc_type":          d["doc_type"],
            "report_categories": d.get("report_categories") or [],
            "document_date":     d.get("document_date"),
            "created_at":        d["created_at"],
            "hospital_label":    d.get("hospital_label"),
            "doctor_label":      d.get("doctor_label"),
            "private":           d["id"] in hidden,
            "private_by_rule":   d["id"] in hidden and d["id"] not in locked_ids,
            "revealed_for_visit": d["id"] in hidden and d["id"] in shown_now,
        } for d in docs]

        # ── whole-vault aggregates (the readout + Hide-all/Show-all + facets) ─
        cat_counts, kind_counts, months = Counter(), Counter(), set()
        shown_ct = visit_ct = private_ct = 0
        showable_ids, hideable_ids = [], []
        for r in rows:
            seen = (not r["private"]) or r["revealed_for_visit"]
            if seen:
                shown_ct += 1
            if r["revealed_for_visit"]:
                visit_ct += 1
            if r["private"] and not r["revealed_for_visit"]:
                private_ct += 1
            if r["private"] and not r["private_by_rule"]:
                showable_ids.append(r["id"])
            hideable_ids.append(r["id"])
            for c in r["report_categories"]:
                if c in _PANEL_RANK:
                    cat_counts[c] += 1
            kind_counts[r["doc_type"]] += 1
            mk = _row_date_key(r)[:7]
            if mk:
                months.add(mk)

        # ── filter (server-authoritative; the client no longer filters) ──────
        q = (request.query_params.get("q") or "").strip().lower()
        cats_f = {s for s in (request.query_params.get("category") or "").split(",") if s}
        kinds_f = {s for s in (request.query_params.get("kind") or "").split(",") if s}
        month_f = (request.query_params.get("month") or "").strip()

        def _keep(r):
            if cats_f and not (set(r["report_categories"]) & cats_f):
                return False
            if kinds_f and r["doc_type"] not in kinds_f:
                return False
            if month_f and _row_date_key(r)[:7] != month_f:
                return False
            if q:
                hay = " ".join(x for x in (r["title"], r["hospital_label"], r["doctor_label"]) if x).lower()
                if q not in hay:
                    return False
            return True

        filtered = [r for r in rows if _keep(r)]

        try:
            page = int(request.query_params.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query_params.get("page_size", _PRIVACY_PAGE_ROWS))
        except (TypeError, ValueError):
            page_size = _PRIVACY_PAGE_ROWS
        page_size = max(10, min(page_size, _PRIVACY_PAGE_MAX))

        page_rows, pmeta = _paginate_groups(_bucket_groups(filtered), page, page_size)

        return success(data={
            "hide_all":          p.hide_all,
            "hidden_categories": p.hidden_categories or [],
            "hidden_kinds":      p.hidden_kinds or [],
            "hidden_sections":   p.hidden_sections or [],
            "sections":          list(RecordsPrivacy.SECTIONS),
            "section_labels":    _SECTION_LABELS,
            "documents":         page_rows,
            "pagination":        pmeta,
            "summary": {
                "vault_total":     len(rows),
                "filtered_total":  len(filtered),
                "shown":           shown_ct,
                "visit":           visit_ct,
                "private":         private_ct,
                "showable_ids":    showable_ids,
                "hideable_ids":    hideable_ids,
                "filtered_ids":    [r["id"] for r in filtered],
                "category_counts": dict(cat_counts),
                "kind_counts":     dict(kind_counts),
                "category_labels": {c: _panel_label(c) for c in cat_counts},
                "kind_labels":     {k: _KIND_LABEL.get(k, "Documents") for k in kind_counts},
                "months":          sorted(months, reverse=True),
                "truncated":       len(docs) >= _PRIVACY_VAULT_MAX,
            },
            "active_session": ({
                "token":             live.token,
                "requester_label":   live.requester_label,
                "seconds_left":      live.seconds_left(),
                "shown_private_ids": live.shown_private_ids or [],
            } if live else None),
        })

    def put(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)

        p = RecordsPrivacy.for_awpid(me)
        d = request.data
        fields = ["updated_at"]

        if "hide_all" in d:
            p.hide_all = bool(d["hide_all"]); fields.append("hide_all")
        if "hidden_categories" in d:
            p.hidden_categories = [str(s) for s in (d["hidden_categories"] or [])][:60]
            fields.append("hidden_categories")
        if "hidden_kinds" in d:
            valid = dict(SharedDocument.DOC_TYPE_CHOICES)
            p.hidden_kinds = [k for k in (d["hidden_kinds"] or []) if k in valid]
            fields.append("hidden_kinds")
        if "hidden_sections" in d:
            p.hidden_sections = [s for s in (d["hidden_sections"] or []) if s in RecordsPrivacy.SECTIONS]
            fields.append("hidden_sections")
        if "hidden_doc_ids" in d:
            want = {int(x) for x in (d["hidden_doc_ids"] or []) if str(x).lstrip("-").isdigit()}
            mine = set(
                SharedDocument.objects.using("default")
                .filter(awpid=me, id__in=want).values_list("id", flat=True)
            )
            p.hidden_doc_ids = sorted(mine); fields.append("hidden_doc_ids")

        # Incremental bulk lock/unlock — the privacy screen is paged now, so the
        # client can't send a full replacement list; it sends deltas instead.
        if "add_hidden_doc_ids" in d or "remove_hidden_doc_ids" in d:
            cur = set(p.hidden_doc_ids or [])
            add = {int(x) for x in (d.get("add_hidden_doc_ids") or []) if str(x).lstrip("-").isdigit()}
            rem = {int(x) for x in (d.get("remove_hidden_doc_ids") or []) if str(x).lstrip("-").isdigit()}
            if add:
                cur |= set(
                    SharedDocument.objects.using("default")
                    .filter(awpid=me, id__in=add).values_list("id", flat=True)
                )
            cur -= rem
            p.hidden_doc_ids = sorted(cur)
            if "hidden_doc_ids" not in fields:
                fields.append("hidden_doc_ids")

        p.save(using="default", update_fields=fields)
        _audit(me, EmergencyAccessLog.EVENT_PRIVACY, _client_ip(request))
        return success(data={"ok": True})


class RecordsPrivacyToggleView(APIView):
    """
    POST /api/v1/portal/records-privacy/toggle/   body { doc_id, private }

    The single-record lock used from My Reports — add or remove one
    SharedDocument id from the standing hidden list.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)
        try:
            doc_id = int(request.data.get("doc_id"))
        except (TypeError, ValueError):
            return error("Which report?", errors={"doc_id": "Required."})
        if not SharedDocument.objects.using("default").filter(awpid=me, id=doc_id).exists():
            return error("That report isn't in your records.", status=404)

        make_private = bool(request.data.get("private"))
        p = RecordsPrivacy.for_awpid(me)
        ids = set(p.hidden_doc_ids or [])
        ids.add(doc_id) if make_private else ids.discard(doc_id)
        p.hidden_doc_ids = sorted(ids)
        p.save(using="default", update_fields=["hidden_doc_ids", "updated_at"])
        _audit(me, EmergencyAccessLog.EVENT_PRIVACY, _client_ip(request))
        return success(data={"doc_id": doc_id, "private": make_private})


class RecordsShareRevealView(APIView):
    """
    POST /api/v1/portal/records-share/<token>/reveal/
      body { doc_ids: [..], scope: "visit" | "always" | "conceal" }

    visit    — show these to the doctor for THIS live visit only; they drop
               back to private when the visit ends.
    always   — also clear them from standing privacy (visible to future
               doctors too).
    conceal  — undo a this-visit reveal now.
    """
    permission_classes = [IsPatient]

    def post(self, request, token):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)
        if grant.awpid and grant.awpid != me:
            return error("This isn't your access grant.", status=403)
        if not grant.is_live:
            return error("This access has ended.", status=403)

        scope = (request.data.get("scope") or "visit").strip()
        if scope not in ("visit", "always", "conceal"):
            scope = "visit"
        want = {int(x) for x in (request.data.get("doc_ids") or []) if str(x).lstrip("-").isdigit()}
        ids = set(
            SharedDocument.objects.using("default")
            .filter(awpid=me, id__in=want).values_list("id", flat=True)
        )

        shown = set(grant.shown_private_ids or [])
        shown = (shown - ids) if scope == "conceal" else (shown | ids)
        grant.shown_private_ids = sorted(shown)
        grant.save(using="default", update_fields=["shown_private_ids"])

        if scope == "always" and ids:
            p = RecordsPrivacy.for_awpid(me)
            p.hidden_doc_ids = sorted(set(p.hidden_doc_ids or []) - ids)
            p.save(using="default", update_fields=["hidden_doc_ids", "updated_at"])

        _audit(me, EmergencyAccessLog.EVENT_PRIVACY, _client_ip(request))
        return success(data={"shown_private_ids": grant.shown_private_ids})
