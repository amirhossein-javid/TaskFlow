from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connection

from apps.accounts.models import Profile, User

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_profile_repairs_create_exactly_one_profile_per_user():
    healthy = User.objects.create_user("healthy@example.com")
    Profile.objects.filter(user=healthy).update(full_name="Existing name")
    original = Profile.objects.filter(user=healthy).values().get()
    User.objects.bulk_create([User(email=f"missing-{index}@example.com") for index in range(3)])
    barrier = Barrier(2)

    def repair():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
            barrier.wait(timeout=5)
            call_command("repair_profiles", stdout=StringIO())
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(repair) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)

    assert Profile.objects.count() == User.objects.count() == 4
    assert not User.objects.filter(profile__isnull=True).exists()
    assert Profile.objects.filter(user=healthy).values().get() == original
