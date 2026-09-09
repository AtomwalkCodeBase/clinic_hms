# v7 table-count redesign: drop the three old billing dropdown tables now
# that 0008 has copied every row into OptionList.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0008_migrate_option_lists_data'),
    ]

    operations = [
        migrations.DeleteModel(
            name='InvoiceStatusOption',
        ),
        migrations.DeleteModel(
            name='PaymentModeOption',
        ),
        migrations.DeleteModel(
            name='ServiceCategory',
        ),
    ]
