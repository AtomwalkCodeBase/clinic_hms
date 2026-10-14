"""
apps/org/models.py
------------------
Hospital DB models for organisational structure.

Tables: Branch, Department, StaffUser, DoctorProfile

Notes:
  - StaffUser extends Django's User (stored per-hospital).
  - set_unusable_password() is called on creation — staff set their own passwords
    via the self-service setup-password endpoint.
  - Branch.lat/lng for map display.
"""

from django.db import models


class NextNumber(models.Model):
    """
    NNTM — Next Number Table Manager.
    One row per (branch, entity) pair. Lives in hospital DB (app_label="org").
    get_next_number() in core/utils/nntm.py uses SELECT FOR UPDATE for uniqueness.

    Entities: uhid, invoice, lab_report, prescription, queue
    """
    branch_id   = models.IntegerField(db_index=True)
    entity      = models.CharField(max_length=20)
    prefix      = models.CharField(max_length=10, default="")
    last_number = models.PositiveBigIntegerField(default=0)
    pad_length  = models.PositiveSmallIntegerField(default=6)

    class Meta:
        db_table     = "next_number"
        unique_together = [("branch_id", "entity")]

    def __str__(self):
        return f"{self.prefix}{str(self.last_number).zfill(self.pad_length)}"

class Branch(models.Model):
    """A physical location of the hospital."""
    name        = models.CharField(max_length=200)
    address     = models.TextField(blank=True)
    city        = models.CharField(max_length=100, blank=True)
    state       = models.CharField(max_length=100, blank=True)
    pincode     = models.CharField(max_length=10, blank=True)
    phone       = models.CharField(max_length=20, blank=True)
    lat         = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng         = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "branch"

    def __str__(self):
        return self.name

class Department(models.Model):
    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE,
                                    related_name="departments")
    name        = models.CharField(max_length=100)
    is_active   = models.BooleanField(default=True)

    class Meta:
        db_table  = "department"
        unique_together = [("branch", "name")]

    def __str__(self):
        return f"{self.branch.name} / {self.name}"

class Floor(models.Model):
    """
    A physical floor at a branch — e.g. "Ground", "1st Floor", "Basement".
    Lets hospital admin set up how many floors a branch has once, then
    assign Rooms (OPD consultation rooms AND bed-based IPD rooms/wards —
    see Room's own docstring) to one of them from a dropdown instead of
    retyping free text on every room. `level` is a plain
    sort key (Ground=0, 1st=1, 2nd=2, Basement=-1, …) — not enforced
    unique, since two floors could reasonably share a label in edge cases
    (e.g. two basements); the (branch, name) constraint below is what
    actually prevents duplicates in normal use.
    """
    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="floors")
    name        = models.CharField(max_length=50)    # e.g. "Ground", "1st Floor"
    level       = models.IntegerField(default=0)      # sort order only
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "floor"
        unique_together = [("branch", "name")]
        ordering  = ["level", "name"]

    def __str__(self):
        return f"{self.name} ({self.branch.name})"

class Room(models.Model):
    """
    A physical room at a branch, on a given floor — OPD consultation/
    procedure space AND (since the v8 unification) inpatient wards/ICU/etc.
    too. Doctors are NOT assigned here directly — a room can be shared by
    several doctors across the week (see RoomAssignment). This table is
    just the room's own identity (which floor, what it's called, what kind
    of room, and — for a bed-based room type — how many beds it can hold).

    Previously "IPD space" was a wholly separate `Ward` model with its own
    `ward_type` catalog and its own Bed FK. That split didn't reflect
    anything physically different about the two kinds of room — a room is
    a room; what differs is what it's used for and whether patients stay
    overnight in it — so Ward was folded in here (see the org 0025-0028
    migrations for the schema/data migration, and billing.OptionList's
    docstring for how room_type absorbed ward_type). A hospital-admin
    "Ward 1" from before this migration is now just a Room whose room_type
    is a bed-based one (e.g. "General Ward").

    # Was a fixed choices= list (consultation/procedure/other) — now
    # hospital-configurable via billing.OptionList(list_type="room_type"),
    # same mechanism as Invoice.status / Payment.payment_mode / Drug.form.
    # Validated at the view layer (org.views.RoomListCreateView/RoomDetailView),
    # not here, since a DB choices= constraint can't be extended per-hospital.
    """

    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="rooms")
    floor       = models.CharField(max_length=30, blank=True)   # legacy free-text mirror of floor_obj.name — kept so
                                                                  # existing readers (RoomAssignmentSerializer, etc.)
                                                                  # keep working unchanged; views.py keeps it in sync
    floor_obj   = models.ForeignKey(Floor, on_delete=models.SET_NULL, null=True, blank=True, related_name="rooms")
    # Optional — most OPD rooms don't need one; a bed-based room (ward/ICU/
    # etc.) commonly does, same role Ward.department used to play.
    department  = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="rooms")
    name        = models.CharField(max_length=100)              # e.g. "Room 204", "OPD-3", "Ward 1", "ICU-A"
    room_type   = models.CharField(max_length=20, default="consultation")
    # Max number of active Beds this room may hold — only meaningful (and
    # required at the view layer) when room_type's billing.OptionList row
    # has is_bed_based=True; stays null for OPD-style rooms. Enforced
    # wherever a Bed is added to or moved into a room (org.views.
    # BedListCreateView.post / BedDetailView.patch) — same role
    # Ward.capacity used to play.
    capacity    = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "room"
        unique_together = [("branch", "name")]
        ordering  = ["floor", "name"]

    def __str__(self):
        return f"{self.name} (Floor {self.floor or '—'}, {self.branch.name})"


class Bed(models.Model):
    """
    One physical bed within a Room (a bed-based one — general ward/private/
    ICU/etc., per its room_type's billing.OptionList.is_bed_based flag).
    status is the single source of truth for "can this bed be assigned
    right now" — ipd.views.AssignBedView is the only place that flips it to
    occupied, and discharge/transfer flows (Phase 2) are what would flip it
    back. Deliberately simple (no per-bed equipment/rate fields yet) — this
    is the minimum needed to let an Admission move off "awaiting bed", not
    a full bed-management module.

    Used to hang off a separate `Ward` model (`ward` FK) — Ward was folded
    into Room (see Room's own docstring and the org 0025-0028 migrations),
    so this FK now points at Room directly. `ward_name`-shaped readers
    elsewhere (apps/ipd/serializers.py, apps/ipd/views.py) were updated to
    read `bed.room.name` instead.

    The "Phase 2" this docstring used to point at (discharge/transfer flows
    that flip status back off `occupied`) is now built — see
    apps.hospital_master.ipd.views.DischargeAdmissionView (-> cleaning, not straight back to
    available), apps.hospital_master.ipd.views.TransferBedView (atomic bed-to-bed move), and
    apps.hospital_master.staff.views.BedMarkCleanView (cleaning -> available, front desk
    confirms the bed's actually ready). `reserved` is new too: a bed can be
    earmarked for one specific, not-yet-bedded Admission (see
    apps.hospital_master.ipd.views.ReserveBedView) before it's physically occupied, e.g.
    while its current occupant is still being discharged/cleaned out.
    """
    STATUS_AVAILABLE      = "available"
    STATUS_RESERVED       = "reserved"
    STATUS_OCCUPIED       = "occupied"
    STATUS_CLEANING       = "cleaning"
    STATUS_BLOCKED        = "blocked"
    STATUS_OUT_OF_SERVICE = "out_of_service"
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Available"),
        (STATUS_RESERVED, "Reserved"),
        (STATUS_OCCUPIED, "Occupied"),
        (STATUS_CLEANING, "Cleaning"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_OUT_OF_SERVICE, "Out of Service"),
    ]

    # Documents intent; the actual guard is each view only ever writing one
    # specific transition (same style as Admission.ALLOWED_TRANSITIONS) —
    # kept here too so a frontend/reporting reader has one place to check
    # "is X -> Y even a real transition" without reading every view.
    ALLOWED_TRANSITIONS = {
        STATUS_AVAILABLE: [STATUS_RESERVED, STATUS_OCCUPIED, STATUS_BLOCKED, STATUS_OUT_OF_SERVICE],
        STATUS_RESERVED: [STATUS_OCCUPIED, STATUS_AVAILABLE],
        # AVAILABLE is kept here (alongside CLEANING) for ReleaseBedView's
        # "administrative undo" case — a bed assigned in error was never
        # really occupied, so it doesn't need a cleaning step.
        STATUS_OCCUPIED: [STATUS_CLEANING, STATUS_AVAILABLE],
        STATUS_CLEANING: [STATUS_AVAILABLE],
        STATUS_BLOCKED: [STATUS_AVAILABLE],
        STATUS_OUT_OF_SERVICE: [STATUS_AVAILABLE],
    }

    room        = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="beds")
    bed_number  = models.CharField(max_length=20)   # e.g. "3A", "12"
    status      = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_AVAILABLE, db_index=True)
    # Set only while status=RESERVED, by apps.hospital_master.ipd.views.ReserveBedView, and
    # cleared the moment that reservation is either confirmed (AssignBedView)
    # or cancelled (CancelBedReservationView). A plain UUID, not a real FK —
    # apps.hospital_master.staff sits below apps.hospital_master.ipd in the app hierarchy (apps.hospital_master.ipd imports
    # apps.hospital_master.staff.models, not the other way around; see Bed's sibling
    # BedSerializer.get_current_admission for the same documented
    # one-directional exception used read-only). Matches this codebase's
    # existing convention of not adding cross-app FKs the "wrong" way
    # (e.g. opd.Appointment.patient_id).
    reserved_for_admission_id = models.UUIDField(null=True, blank=True, db_index=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "bed"
        unique_together = [("room", "bed_number")]
        ordering  = ["room__name", "bed_number"]

    def __str__(self):
        return f"{self.room.name} / Bed {self.bed_number} ({self.status})"
