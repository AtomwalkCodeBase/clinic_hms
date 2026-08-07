from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0003_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffEmailIndex",
            fields=[
                ("id",         models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("email",      models.EmailField(db_index=True, max_length=254, unique=True)),
                ("tenant_id",  models.IntegerField()),
                ("db_name",    models.CharField(max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table":  "staff_email_index",
                "app_label": "registry",
            },
        ),
    ]
