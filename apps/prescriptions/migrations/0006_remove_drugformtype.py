# v7 table-count redesign: DrugFormType merged into
# apps.billing.OptionList(list_type="drug_form"). Depends on billing's
# 0008 data-copy migration so this table isn't dropped before its rows
# have been copied across.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('prescriptions', '0005_drug_default_mrp'),
        ('billing', '0008_migrate_option_lists_data'),
    ]

    operations = [
        migrations.DeleteModel(
            name='DrugFormType',
        ),
    ]
