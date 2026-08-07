from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("org", "0002_staffuser_must_change_password"),
    ]

    operations = [
        migrations.CreateModel(
            name="NextNumber",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("branch_id", models.IntegerField(db_index=True)),
                ("entity", models.CharField(max_length=20)),
                ("prefix", models.CharField(default="", max_length=10)),
                ("last_number", models.PositiveBigIntegerField(default=0)),
                ("pad_length", models.PositiveSmallIntegerField(default=6)),
            ],
            options={
                "db_table": "next_number",
                "app_label": "org",
                "unique_together": {("branch_id", "entity")},
            },
        ),
    ]
