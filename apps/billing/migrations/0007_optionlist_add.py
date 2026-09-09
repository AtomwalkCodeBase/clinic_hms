# v7 table-count redesign: create the merged OptionList table.
# Old ServiceCategory/PaymentModeOption/InvoiceStatusOption tables are kept
# alive until 0009, once 0008 has copied their rows across.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0006_remove_invoice_encounter'),
    ]

    operations = [
        migrations.CreateModel(
            name='OptionList',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('list_type', models.CharField(choices=[('service_category', 'Service Category'), ('payment_mode', 'Payment Mode'), ('invoice_status', 'Invoice Status'), ('drug_form', 'Drug Form')], db_index=True, max_length=20)),
                ('value', models.CharField(max_length=20)),
                ('label', models.CharField(max_length=50)),
                ('is_active', models.BooleanField(default=True)),
                ('is_system', models.BooleanField(default=False)),
                ('sort_order', models.PositiveSmallIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'option_list',
                'ordering': ['list_type', 'sort_order', 'label'],
            },
        ),
        migrations.AddConstraint(
            model_name='optionlist',
            constraint=models.UniqueConstraint(fields=('list_type', 'value'), name='uniq_option_list_type_value'),
        ),
    ]
