from django.db import migrations


def backfill_profiles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Profile = apps.get_model("accounts", "Profile")

    for user in User.objects.using(schema_editor.connection.alias).iterator():
        Profile.objects.using(schema_editor.connection.alias).update_or_create(
            user_id=user.pk,
            defaults={"full_name": user.full_name},
        )


def restore_full_names(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Profile = apps.get_model("accounts", "Profile")

    for profile in Profile.objects.using(schema_editor.connection.alias).iterator():
        User.objects.using(schema_editor.connection.alias).filter(pk=profile.user_id).update(
            full_name=profile.full_name
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_create_profile"),
    ]

    operations = [
        migrations.RunPython(backfill_profiles, restore_full_names),
    ]
