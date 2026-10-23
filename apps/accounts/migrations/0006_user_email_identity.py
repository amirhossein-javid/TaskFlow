from django.db import migrations, models
from django.db.models.functions import Lower, Trim


def normalize_existing_emails(apps, schema_editor):
    user = apps.get_model("accounts", "User")
    alias = schema_editor.connection.alias
    # Keep the collision preflight, normalization, and constraint installation
    # atomic with respect to writes from an older application version.
    schema_editor.execute(
        f"LOCK TABLE {schema_editor.quote_name(user._meta.db_table)} IN ACCESS EXCLUSIVE MODE"
    )
    users = user.objects.using(alias).annotate(canonical_email=Lower(Trim("email")))
    duplicates = list(
        users.values("canonical_email")
        .annotate(total=models.Count("pk"))
        .filter(total__gt=1)
        .values_list("canonical_email", flat=True)
    )
    if duplicates:
        ids = list(
            users.filter(canonical_email__in=duplicates).order_by("pk").values_list("pk", flat=True)
        )
        raise RuntimeError(
            f"Resolve email identity collisions for user IDs {ids} before retrying migration. "
            "No accounts were merged or deleted."
        )
    user.objects.using(alias).update(email=Lower(Trim("email")))


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_alter_profile_options_alter_user_options_and_more")]

    operations = [
        migrations.RunPython(normalize_existing_emails, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower(Trim("email")),
                name="unique_user_email_ci",
                violation_error_message="کاربری با این ایمیل وجود دارد.",
            ),
        ),
    ]
