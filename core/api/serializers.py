import re

from rest_framework import serializers


def _snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class PkModelSerializer(serializers.ModelSerializer):
    """ModelSerializer where a field named <model>_id (room_id, branch_id, ...) is that row's primary key. The API keeps these prefixed names while the models use the plain `id`."""

    def build_unknown_field(self, field_name, model_class):
        if field_name in (_snake(model_class.__name__) + "_id", model_class._meta.db_table + "_id"):
            return serializers.IntegerField, {"source": "pk", "read_only": True}
        return super().build_unknown_field(field_name, model_class)
