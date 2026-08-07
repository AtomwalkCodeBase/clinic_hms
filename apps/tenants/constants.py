"""
apps/tenants/constants.py
--------------------------
Single source of truth for per-tier feature gates and soft limits.

Previously this dict was duplicated byte-for-byte in platform_admin/views.py
and provision_tenant.py — two independent copies that could silently drift
out of sync with each other and with the real, enforced values (a starter
tier edited in one place but not the other would misreport its own limits).
Both now import from here.

Keys map 1:1 to Subscription model fields (spread directly into
Subscription.objects.create(**TIER_FEATURE_DEFAULTS[tier])), so adding a
new tier-scoped field means adding it to both the Subscription model and
every tier's dict here.
"""

TIER_FEATURE_DEFAULTS = {
    "starter": {
        "feat_lab": False, "feat_pharmacy": False, "feat_whatsapp": False,
        "feat_multi_branch": False, "feat_ai_voice": False, "feat_patient_app": False,
        "feat_analytics": False, "feat_video": False, "feat_face_recog": False,
        "feat_custom_roles": False,
        "max_doctors": 3, "max_branches": 1, "max_staff": 5,
    },
    "growth": {
        "feat_lab": True, "feat_pharmacy": True, "feat_whatsapp": True,
        "feat_multi_branch": False, "feat_ai_voice": False, "feat_patient_app": False,
        "feat_analytics": False, "feat_video": False, "feat_face_recog": False,
        "feat_custom_roles": False,
        "max_doctors": 10, "max_branches": 1, "max_staff": 15,
    },
    "pro": {
        "feat_lab": True, "feat_pharmacy": True, "feat_whatsapp": True,
        "feat_multi_branch": True, "feat_ai_voice": True, "feat_patient_app": True,
        "feat_analytics": True, "feat_video": False, "feat_face_recog": False,
        "feat_custom_roles": False,
        "max_doctors": 50, "max_branches": 5, "max_staff": 75,
    },
    "enterprise": {
        "feat_lab": True, "feat_pharmacy": True, "feat_whatsapp": True,
        "feat_multi_branch": True, "feat_ai_voice": True, "feat_patient_app": True,
        "feat_analytics": True, "feat_video": True, "feat_face_recog": True,
        "feat_custom_roles": True,
        "max_doctors": 9999, "max_branches": 999, "max_staff": 9999,
    },
}
