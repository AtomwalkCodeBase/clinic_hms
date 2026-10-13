"""
Vaccination and milestone schedules become ONE pair of tables: vaccination_schedule / vaccination_schedule_rule, with
a `kind` on the schedule. The vaccination tables are renamed in place (ids unchanged); the milestone rows are copied in
with new ids, and each Tenant.active_milestone_schedule_id is re-pointed. The old milestone tables are then dropped.
"""
from django.db import migrations, models
import django.db.models.deletion

_SHARED = ["name", "description", "owner_tenant_id", "is_template", "active", "created_at", "updated_at"]
_RULE = ["scheduled_label", "min_age_days", "max_age_days", "mandatory", "sort_order"]


def _point_tenants(apps, old_to_new):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.using("default").exclude(active_milestone_schedule_id=None):
        new_id = old_to_new.get(tenant.active_milestone_schedule_id)
        if new_id:
            Tenant.objects.using("default").filter(pk=tenant.pk).update(active_milestone_schedule_id=new_id)


def milestones_in(apps, schema_editor):
    Schedule, Rule = apps.get_model("registry", "Schedule"), apps.get_model("registry", "ScheduleRule")
    ids = {}
    for old in apps.get_model("registry", "MilestoneSchedule").objects.using("default").order_by("id"):
        new = Schedule.objects.using("default").create(kind="milestone", **{f: getattr(old, f) for f in _SHARED})
        Schedule.objects.using("default").filter(pk=new.pk).update(created_at=old.created_at, updated_at=old.updated_at)
        ids[old.id] = new.id
    for rule in apps.get_model("registry", "MilestoneScheduleRule").objects.using("default").order_by("sort_order", "id"):
        Rule.objects.using("default").create(schedule_id=ids[rule.schedule_id], item=rule.milestone, domain=rule.domain,
                                             **{f: getattr(rule, f) for f in _RULE})
    _point_tenants(apps, ids)
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")   # Postgres refuses the ALTERs below while FK checks are pending


def milestones_out(apps, schema_editor):
    Schedule = apps.get_model("registry", "Schedule")
    Old, OldRule, ids = apps.get_model("registry", "MilestoneSchedule"), apps.get_model("registry", "MilestoneScheduleRule"), {}
    for new in Schedule.objects.using("default").filter(kind="milestone").order_by("id"):
        old = Old.objects.using("default").create(**{f: getattr(new, f) for f in _SHARED})
        Old.objects.using("default").filter(pk=old.pk).update(created_at=new.created_at, updated_at=new.updated_at)
        ids[new.id] = old.id
        for rule in new.rules.all():
            OldRule.objects.using("default").create(schedule_id=old.id, milestone=rule.item, domain=rule.domain,
                                                    **{f: getattr(rule, f) for f in _RULE})
    _point_tenants(apps, ids)
    Schedule.objects.using("default").filter(kind="milestone").delete()
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0047_consultsession_note_pdf"),
        ("tenants", "0014_tenant_latitude_tenant_longitude"),
    ]

    operations = [
        migrations.RenameModel("VaccinationSchedule", "Schedule"),
        migrations.RenameModel("VaccinationScheduleRule", "ScheduleRule"),
        migrations.AlterModelTable("Schedule", "vaccination_schedule"),
        migrations.AlterModelTable("ScheduleRule", "vaccination_schedule_rule"),
        migrations.AddField("Schedule", "kind", models.CharField(
            max_length=15, default="vaccination", choices=[("vaccination", "Vaccination"), ("milestone", "Milestone")]),
            preserve_default=False),
        migrations.RenameField("ScheduleRule", "vaccine_name", "item"),
        migrations.AlterField("ScheduleRule", "item", models.CharField(max_length=200)),
        migrations.AddField("ScheduleRule", "domain", models.CharField(blank=True, default="", max_length=20, choices=[
            ("gross_motor", "Gross Motor"), ("fine_motor", "Fine Motor"), ("language", "Language / Communication"),
            ("cognitive", "Cognitive"), ("social_emotional", "Social / Emotional")]), preserve_default=False),
        migrations.AlterField("ScheduleRule", "schedule", models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE, related_name="rules", to="registry.schedule")),
        migrations.RunPython(milestones_in, milestones_out),
        migrations.DeleteModel("MilestoneScheduleRule"),
        migrations.DeleteModel("MilestoneSchedule"),
        migrations.CreateModel(name="VaccinationSchedule", fields=[], options={"proxy": True, "indexes": [], "constraints": []},
                               bases=("registry.schedule",)),
        migrations.CreateModel(name="MilestoneSchedule", fields=[], options={"proxy": True, "indexes": [], "constraints": []},
                               bases=("registry.schedule",)),
        migrations.CreateModel(name="VaccinationScheduleRule", fields=[], options={"proxy": True, "indexes": [], "constraints": []},
                               bases=("registry.schedulerule",)),
        migrations.CreateModel(name="MilestoneScheduleRule", fields=[], options={"proxy": True, "indexes": [], "constraints": []},
                               bases=("registry.schedulerule",)),
    ]
