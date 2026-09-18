# Generated for the geolocation "hospitals near me" feature.

"""
Data migration: registers 15 real, independently-run clinics/small
hospitals in the AECS Layout / Munnekollal / Marathahalli / Bellandur /
Mahadevapura / Whitefield belt of East Bengaluru, so "Find a Hospital" has
enough real geographic spread near there to actually demonstrate
distance-based sorting.

Names, addresses (to the precision a free geocoder could resolve — street
or landmark level for most, locality level for a few marked below) and
coordinates were looked up, not invented. Two fields are deliberately left
blank rather than guessed:
  - accreditations: this platform has no way to verify a third-party
    clinic's real NABH/ISO status, so claiming one would be misinformation.
  - gstin: not public information.

These rows only ever touch the registry ("default") database — no
per-tenant Postgres database is created here. Creating one is a heavier,
transactional-unsafe operation (see apps.tenants.utils.create_tenant_database's
own docstring: "must be called outside any transaction block") that this
codebase already does at request time via the platform-admin "provision a
new hospital" flow, not inside a schema migration — and on a managed cloud
Postgres the app's own DB user often can't CREATE DATABASE at all, so doing
it here would silently break on exactly the "run on cloud too" environments
this migration needs to work in. Practical effect: these hospitals show up
fully in the patient app's hospital list/search/"near me", but their
"View doctors" list is empty until a platform admin runs them through the
real onboarding flow (apps.patients.portal_views.PortalDoctorListView
already degrades to an empty list instead of erroring when a tenant's
database doesn't exist yet).

Idempotent by design (keyed on `name`, not row id) so re-running this
against an environment that already has some of these rows — e.g. local
dev after seed_investor_demo — updates rather than duplicates them.
"""
from django.db import migrations


# (name, city, about, latitude, longitude)
# about text is original wording, not copied from any listing.
CLINICS = [
    (
        "Brookefield Hospitals",  # already exists in most dev environments
        # (seeded by seed_investor_demo/seed_full_demo with no profile
        # filled in) — matched here to the real Brookefield Hospital on
        # ITPL Main Road, Kundalahalli, so this migration completes its
        # profile instead of creating a duplicate.
        "Bengaluru",
        "Multi-speciality hospital on ITPL Main Road, Kundalahalli, serving the AECS Layout / Brookefield neighbourhood.",
        12.9673, 77.7168,
    ),
    (
        "Aayug Multi Specialty Hospital",
        "Bengaluru",
        "Multi-speciality hospital in B Block, AECS Layout, Kundalahalli.",
        12.9668, 77.7160,
    ),
    (
        "AECS Dental",
        "Bengaluru",
        "Dental clinic on 60 Feet Road, AECS Layout D Block.",
        12.9642, 77.7137,
    ),
    (
        "Ratnatulasi Dental Clinic",
        "Bengaluru",
        "Dental clinic on 9th Main, Manjunatha Layout, Munnekollal.",
        12.9641, 77.7130,  # locality-level: AECS Layout / Munnekollal boundary
    ),
    (
        "Family Care Homeopathy Clinic & Pharmacy",
        "Bengaluru",
        "Homeopathy clinic and pharmacy on Munnekollal Main Road.",
        12.9567, 77.7046,
    ),
    (
        "The Family Doctor & The Family Pharma",
        "Bengaluru",
        "General physician clinic and in-house pharmacy, AECS Layout / Marathahalli.",
        12.9552, 77.6984,  # locality-level: Marathahalli
    ),
    (
        "SVM Hospital",
        "Bengaluru",
        "Sri Vishweshathirtha Memorial Hospital — multi-speciality hospital in C Block, Northern Suites, Marathahalli.",
        12.9575, 77.7010,  # locality-level: Marathahalli
    ),
    (
        "Sri Krishna Sevashrama Trust Hospital",
        "Bengaluru",
        "Trust-run hospital on Outer Ring Road, Marathahalli, near Innovative Multiplex.",
        12.9520, 77.6986,
    ),
    (
        "Nurture Multispeciality Clinic",
        "Bengaluru",
        "Multi-speciality clinic in Doddakannelli, on Bellandur Main Road.",
        12.9115, 77.6934,  # locality-level: Doddakannelli
    ),
    (
        "Dr. Sunny Medical Multispecialty Center",
        "Bengaluru",
        "Multi-speciality clinic in Mint Plaza, Green Glen Layout, Sarjapur Outer Ring Road.",
        12.9269, 77.6699,
    ),
    (
        "Care & Cure Clinic",
        "Bengaluru",
        "General clinic serving the Bellandur neighbourhood.",
        12.9320, 77.6843,  # locality-level: Bellandur
    ),
    (
        "Krishna Healthcare",
        "Bengaluru",
        "Outpatient and daycare specialty clinic on Mahadevapura Main Road, Maheshwari Nagar.",
        12.9918, 77.6902,
    ),
    (
        "Nationwide Family Doctors",
        "Bengaluru",
        "Multi-speciality family clinic serving the Mahadevapura neighbourhood.",
        12.9965, 77.6927,  # locality-level: Mahadevapura
    ),
    (
        "Sri Lakshmi Family Dental Clinic",
        "Bengaluru",
        "Dental clinic on Outer Ring Road, Mahadevapura, open since 2005.",
        12.9863, 77.6906,
    ),
    (
        "Pushpa Nursing Home",
        "Bengaluru",
        "Family-run nursing home on Whitefield Main Road, serving Whitefield since 1978.",
        12.9689, 77.7495,
    ),
]


def seed_clinics(apps, schema_editor):
    from django.utils.text import slugify

    Tenant = apps.get_model("tenants", "Tenant")
    Subscription = apps.get_model("tenants", "Subscription")

    existing_subdomains = set(Tenant.objects.using("default").values_list("subdomain", flat=True))

    for name, city, about, lat, lng in CLINICS:
        tenant = Tenant.objects.using("default").filter(name=name).first()
        if tenant is None:
            base_slug = slugify(name) or "clinic"
            subdomain = base_slug
            suffix = 2
            while subdomain in existing_subdomains:
                subdomain = f"{base_slug}-{suffix}"
                suffix += 1
            existing_subdomains.add(subdomain)
            tenant = Tenant.objects.using("default").create(
                name=name,
                subdomain=subdomain,
                db_name=f"aw_{subdomain.replace('-', '_')}",
                city=city,
                state="Karnataka",
                about=about,
                latitude=lat,
                longitude=lng,
                is_active=True,
            )
        else:
            tenant.city = city
            tenant.state = tenant.state or "Karnataka"
            tenant.about = tenant.about or about
            tenant.latitude = lat
            tenant.longitude = lng
            tenant.is_active = True
            tenant.save(using="default")

        sub, created = Subscription.objects.using("default").get_or_create(
            tenant=tenant,
            defaults={
                "license_tier": "starter",
                "status": "active",
                "feat_patient_app": True,
                "max_doctors": 3, "max_branches": 1, "max_staff": 5,
            },
        )
        if not created and not sub.feat_patient_app:
            sub.feat_patient_app = True
            sub.save(using="default", update_fields=["feat_patient_app"])


def unseed_clinics(apps, schema_editor):
    # Reverse only removes the 14 rows this migration created fresh —
    # "Brookefield Hospitals" is left in place either way since it may
    # predate this migration (seeded by an unrelated demo command).
    # Subscription.tenant is on_delete=PROTECT (see
    # apps.platform_admin.views._teardown_failed_tenant for the same
    # ordering requirement), so its row must go before the Tenant row.
    Tenant = apps.get_model("tenants", "Tenant")
    Subscription = apps.get_model("tenants", "Subscription")
    names = [name for name, *_ in CLINICS if name != "Brookefield Hospitals"]
    tenants = Tenant.objects.using("default").filter(name__in=names)
    Subscription.objects.using("default").filter(tenant__in=tenants).delete()
    tenants.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0014_tenant_latitude_tenant_longitude"),
    ]

    operations = [
        migrations.RunPython(seed_clinics, unseed_clinics),
    ]
