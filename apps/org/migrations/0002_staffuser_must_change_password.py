from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("org", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="staffuser",
            name="must_change_password",
            field=models.BooleanField(default=False),
        ),
    ]
