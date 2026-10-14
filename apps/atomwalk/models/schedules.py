"""The immunization and milestone schedules (one table pair, with a `kind`) and the rules in them."""

from django.db import models


class Schedule(models.Model):
    """
    A named, ordered set of rules a hospital's pediatric roadmap is built against. ONE table for both kinds:
    kind="vaccination" (what to give and when) or kind="milestone" (what a child should be doing and when).

    owner_hospital_id is null for a system template (platform admin maintains those) and a Hospital.id for a hospital's own
    editable copy; is_template marks one meant to be cloned. Hospital.active_vaccination_schedule_id /
    active_milestone_schedule_id point at the live one. Plain IntegerField, not an FK, like the rest of the atomwalk.
    """
    KIND_VACCINATION = "vaccination"
    KIND_MILESTONE   = "milestone"
    KIND_CHOICES = [(KIND_VACCINATION, "Vaccination"), (KIND_MILESTONE, "Milestone")]

    kind            = models.CharField(max_length=15, choices=KIND_CHOICES)
    name            = models.CharField(max_length=200)
    description     = models.TextField(blank=True)
    owner_hospital_id = models.IntegerField(null=True, blank=True)  # null = system-level template
    is_template     = models.BooleanField(default=False)
    active          = models.BooleanField(default=True)  # soft-disable instead of delete
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "immunization_schedules"

    def __str__(self):
        return self.name


class ScheduleRule(models.Model):
    """
    One slot in a Schedule: a vaccine dose ("BCG", dose 1, "Birth") or a milestone ("Sits without support", domain
    gross_motor, "6 months"). `item` is the vaccine or milestone name; vaccine_name / milestone read and write it, so
    callers keep their own word for it. dose_number only matters for vaccines, domain only for milestones.

    min_age_days / max_age_days only drive the informational "upcoming / due now" timing on a slot with no record; they
    never produce an "overdue" verdict (see vaccine_schedule.py).
    """
    DOMAIN_GROSS_MOTOR = "gross_motor"
    DOMAIN_FINE_MOTOR  = "fine_motor"
    DOMAIN_LANGUAGE    = "language"
    DOMAIN_COGNITIVE   = "cognitive"
    DOMAIN_SOCIAL      = "social_emotional"
    DOMAIN_CHOICES = [
        (DOMAIN_GROSS_MOTOR, "Gross Motor"),
        (DOMAIN_FINE_MOTOR,  "Fine Motor"),
        (DOMAIN_LANGUAGE,    "Language / Communication"),
        (DOMAIN_COGNITIVE,   "Cognitive"),
        (DOMAIN_SOCIAL,      "Social / Emotional"),
    ]

    schedule         = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name="rules")
    item             = models.CharField(max_length=200)
    dose_number      = models.PositiveIntegerField(default=1)
    domain           = models.CharField(max_length=20, blank=True, choices=DOMAIN_CHOICES)
    scheduled_label  = models.CharField(max_length=50)   # human age-window label, e.g. "Birth", "6 weeks", "9 months"
    min_age_days     = models.PositiveIntegerField()
    max_age_days     = models.PositiveIntegerField(null=True, blank=True)
    mandatory        = models.BooleanField(default=True)  # false = "nice to note", not a red flag if missed
    sort_order       = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "atomwalk"
        db_table  = "immunization_schedule_rules"
        ordering  = ["sort_order"]

    # the two names callers already use for `item`
    @property
    def vaccine_name(self):
        return self.item

    @vaccine_name.setter
    def vaccine_name(self, value):
        self.item = value

    milestone = vaccine_name

    def save(self, *args, update_fields=None, **kwargs):
        if update_fields is not None:
            update_fields = ["item" if f in ("vaccine_name", "milestone") else f for f in update_fields]
        super().save(*args, update_fields=update_fields, **kwargs)

    def __str__(self):
        return f"{self.schedule.name} — {self.item} ({self.scheduled_label})"


class _OfKind(models.Manager):
    """Rows of one kind only, for the four classes below."""
    def __init__(self, kind, through=""):
        super().__init__()
        self.kind, self.through = kind, through

    def get_queryset(self):
        return super().get_queryset().filter(**{self.through + "kind": self.kind})


class _KindSaved:
    """Mixin for the schedule wrappers: stamps the kind on save."""
    def save(self, *args, **kwargs):
        self.kind = self.KIND
        super().save(*args, **kwargs)


# The names the rest of the code uses; each is the one table, narrowed to its kind.
class VaccinationSchedule(_KindSaved, Schedule):
    KIND = Schedule.KIND_VACCINATION
    objects = _OfKind(KIND)

    class Meta:
        proxy = True
        app_label = "atomwalk"


class MilestoneSchedule(_KindSaved, Schedule):
    KIND = Schedule.KIND_MILESTONE
    objects = _OfKind(KIND)

    class Meta:
        proxy = True
        app_label = "atomwalk"


class VaccinationScheduleRule(ScheduleRule):
    objects = _OfKind(Schedule.KIND_VACCINATION, "schedule__")

    class Meta:
        proxy = True
        app_label = "atomwalk"


class MilestoneScheduleRule(ScheduleRule):
    objects = _OfKind(Schedule.KIND_MILESTONE, "schedule__")

    class Meta:
        proxy = True
        app_label = "atomwalk"
