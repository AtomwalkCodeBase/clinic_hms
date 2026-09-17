from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0032_doc_classify_cache"),
    ]

    operations = [
        migrations.AddField(
            model_name="shareddocument",
            name="review_notes",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
    ]
