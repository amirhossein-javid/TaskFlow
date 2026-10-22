from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection
from django.test import Client
from django.urls import reverse

from apps.accounts.admin import UserAdmin
from apps.accounts.forms import RegistrationForm
from apps.accounts.models import Profile, User

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "StrongPass!2026Task"


@pytest.mark.parametrize("route", ["registration", "admin_add", "admin_change"])
def test_concurrency_email_conflicts_render_validation_errors(route):
    admin = User.objects.create_superuser("admin@example.com", PASSWORD)
    candidates = [User.objects.create_user(f"candidate-{index}@example.com") for index in range(2)]
    barrier = Barrier(2)
    original = RegistrationForm.save if route == "registration" else UserAdmin.save_model

    def synchronized_save(self, *args, **kwargs):
        barrier.wait(timeout=5)
        return original(self, *args, **kwargs)

    def submit(index):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
            client = Client()
            payload = {
                "email": ["RACE@example.com", "race@EXAMPLE.COM"][index],
                "password1": PASSWORD,
                "password2": PASSWORD,
                "full_name": "کاربر",
                "is_active": "on",
            }
            if route == "registration":
                url = reverse("accounts:register")
            else:
                client.force_login(admin)
                url = (
                    reverse("admin:accounts_user_add")
                    if route == "admin_add"
                    else reverse("admin:accounts_user_change", args=[candidates[index].pk])
                )
            response = client.post(url, payload)
            return response.status_code, response.content.decode()
        finally:
            connection.close()

    target = RegistrationForm if route == "registration" else UserAdmin
    method = "save" if route == "registration" else "save_model"
    with patch.object(target, method, synchronized_save):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, index) for index in range(2)]
            results = [future.result(timeout=20) for future in futures]
    assert sorted(status for status, _ in results) == [200, 302]
    assert "کاربری با این ایمیل وجود دارد." in next(
        body for status, body in results if status == 200
    )
    assert User.objects.filter(email__iexact="race@example.com").count() == 1
    assert Profile.objects.count() == User.objects.count()
