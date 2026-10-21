from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_backfill_profiles"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="full_name",
        ),
    ]
