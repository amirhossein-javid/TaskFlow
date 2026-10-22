import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)
OLD = [("accounts", "0005_alter_profile_options_alter_user_options_and_more")]
NEW = [("accounts", "0006_user_email_identity")]


@pytest.fixture
def historical_users():
    executor = MigrationExecutor(connection)
    executor.migrate(OLD)
    apps = executor.loader.project_state(OLD).apps
    user = apps.get_model("accounts", "User")
    try:
        yield user, apps.get_model("accounts", "Profile")
    finally:
        user.objects.all().delete()
        MigrationExecutor(connection).migrate(NEW)


def test_email_migration_normalizes_without_changing_identity(historical_users):
    user, profile = historical_users
    original = user.objects.create(email=" Legacy@EXAMPLE.COM ", password="stored-password-hash")
    profile.objects.create(user=original, full_name="Existing name")
    MigrationExecutor(connection).migrate(NEW)
    original.refresh_from_db()
    assert original.email == "legacy@example.com"
    assert original.password == "stored-password-hash"
    assert profile.objects.get(user_id=original.pk).full_name == "Existing name"
    with pytest.raises(IntegrityError), transaction.atomic():
        user.objects.create(email="LEGACY@example.com")


def test_email_migration_refuses_collisions_without_modifying_accounts(historical_users):
    user, profile = historical_users
    first = user.objects.create(email="Person@example.com", password="first-hash")
    second = user.objects.create(email=" person@EXAMPLE.COM ", password="second-hash")
    profile.objects.create(user=first, full_name="First")
    profile.objects.create(user=second, full_name="Second")
    original_users = list(user.objects.order_by("pk").values())
    original_profiles = list(profile.objects.order_by("pk").values())
    with pytest.raises(RuntimeError, match="Resolve email identity collisions for user IDs"):
        MigrationExecutor(connection).migrate(NEW)
    assert list(user.objects.order_by("pk").values()) == original_users
    assert list(profile.objects.order_by("pk").values()) == original_profiles
