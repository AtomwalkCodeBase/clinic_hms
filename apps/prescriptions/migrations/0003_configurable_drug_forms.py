from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prescriptions', '0002_alter_prescription_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='DrugFormType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'drug_form_type',
                'ordering': ['name'],
            },
        ),
        migrations.AlterField(
            model_name='drug',
            name='form',
            field=models.CharField(default='Tablet', max_length=50),
        ),
    ]
