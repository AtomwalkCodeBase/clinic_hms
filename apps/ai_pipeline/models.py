"""
apps/ai_pipeline/models.py
--------------------------
Retired (HMS-07c-1, as a side effect of retiring apps.clinical.Encounter).
This app was never mounted in atomwalk/urls.py (urls.py was 0 bytes) —
VoiceRecording/AIJob/SuggestionAudit had no live API surface at all, and
their only substantive foreign key was into apps.clinical.Encounter, which
was itself confirmed dead-to-live-traffic and removed. Nothing else in the
codebase referenced this app.

Stays registered in INSTALLED_APPS (empty of models is valid) so its
migration history remains resolvable.
"""
