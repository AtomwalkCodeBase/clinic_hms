from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("records", "0015_no_built_in_types")]

    operations = [
        migrations.AddField("SweepConfig", "min_confidence", models.PositiveSmallIntegerField(default=50)),
        migrations.AddField("SweepConfig", "evidence_scale", models.PositiveSmallIntegerField(default=10)),
        migrations.AlterField("ClassificationRule", "keywords", models.TextField(
            blank=True, help_text="Pipe-separated, e.g. laboratory report^3|glucose|-discharge summary (^N = weight, - = rules out)")),
    ]
