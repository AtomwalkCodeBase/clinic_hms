"""
New ExtractedLabValue table (per-analyte rows read out of a lab_report by
core.lab_value_extractor, via `manage.py extract_lab_values`) + 5 new
extraction_* status/summary fields on SharedDocument.

extraction_* deliberately doesn't follow the existing single
classification_confidence/category_confidence-per-document naming pattern —
confidence here is per VALUE (ExtractedLabValue.confidence), since one report
can have some clean results and some shaky ones; extraction_values_total/
_confident are just a cheap denormalized summary for list views, not a
replacement for per-value confidence.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registry', '0036_merge_20260911_1931'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExtractedLabValue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('awpid', models.CharField(db_index=True, max_length=30)),
                ('document_date', models.DateField(blank=True, null=True)),
                ('parameter_slug', models.CharField(db_index=True, max_length=60)),
                ('parameter_label', models.CharField(max_length=120)),
                ('value_numeric', models.FloatField()),
                ('unit', models.CharField(blank=True, max_length=30)),
                ('reference_range_text', models.CharField(blank=True, max_length=80)),
                ('reference_low', models.FloatField(blank=True, null=True)),
                ('reference_high', models.FloatField(blank=True, null=True)),
                ('confidence', models.FloatField()),
                ('extraction_method', models.CharField(blank=True, max_length=20)),
                ('extracted_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'extracted_lab_value',
            },
        ),
        migrations.AddField(
            model_name='shareddocument',
            name='extracted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shareddocument',
            name='extraction_method',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='shareddocument',
            name='extraction_status',
            field=models.CharField(db_index=True, default='not_attempted', max_length=16),
        ),
        migrations.AddField(
            model_name='shareddocument',
            name='extraction_values_confident',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='shareddocument',
            name='extraction_values_total',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name='shareddocument',
            index=models.Index(fields=['awpid', 'extraction_status'], name='shared_doc_awpid_extract_idx'),
        ),
        migrations.AddField(
            model_name='extractedlabvalue',
            name='document',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lab_values', to='registry.shareddocument'),
        ),
        migrations.AddIndex(
            model_name='extractedlabvalue',
            index=models.Index(fields=['awpid', 'parameter_slug', 'document_date'], name='lab_value_awpid_param_date_idx'),
        ),
    ]
