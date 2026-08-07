from rest_framework import serializers
from apps.registry.models import Tenant, Subscription, User, SubscriptionEvent


class TenantListSerializer(serializers.ModelSerializer):
    license_tier_display = serializers.CharField(source="get_license_tier_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    user_count = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id", "name", "slug", "db_name", "status", "status_display",
            "license_tier", "license_tier_display", "doctor_band",
            "city", "state", "admin_email", "phone",
            "trial_ends_at", "created_at", "user_count", "subscription_status",
        ]

    def get_user_count(self, obj):
        return obj.users.filter(is_active=True).count()

    def get_subscription_status(self, obj):
        try:
            return obj.subscription.status
        except Exception:
            return None


class ProvisionTenantSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=100, required=False)
    city = serializers.CharField(max_length=100, required=False, default="")
    state = serializers.CharField(max_length=100, required=False, default="")
    phone = serializers.CharField(max_length=20, required=False, default="")
    admin_email = serializers.EmailField()
    plan = serializers.ChoiceField(choices=["trial", "essential", "opd_ai", "hospital"], default="trial")
    band = serializers.ChoiceField(choices=["small", "medium", "large"], default="small")

    def validate_slug(self, value):
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError(f"Slug '{value}' is already taken.")
        return value

    def validate(self, data):
        if "slug" not in data or not data.get("slug"):
            from django.utils.text import slugify
            data["slug"] = slugify(data["name"])
        if Tenant.objects.filter(slug=data["slug"]).exists():
            raise serializers.ValidationError({"slug": f"Slug '{data['slug']}' is already taken."})
        return data


class TenantDetailSerializer(serializers.ModelSerializer):
    subscription = serializers.SerializerMethodField()
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = "__all__"

    def get_subscription(self, obj):
        try:
            sub = obj.subscription
            return {
                "plan": sub.plan,
                "band": sub.doctor_band,
                "status": sub.status,
                "mrr_inr": str(sub.mrr_inr),
                "billing_cycle_end": sub.billing_cycle_end,
                "max_doctors": sub.max_doctors,
                "max_ai_minutes_per_month": sub.max_ai_minutes_per_month,
            }
        except Exception:
            return None

    def get_user_count(self, obj):
        return obj.users.filter(is_active=True).count()


class UpdateTenantPlanSerializer(serializers.Serializer):
    plan = serializers.ChoiceField(choices=["trial", "essential", "opd_ai", "hospital"])
    band = serializers.ChoiceField(choices=["small", "medium", "large"])
    notes = serializers.CharField(required=False, default="")
