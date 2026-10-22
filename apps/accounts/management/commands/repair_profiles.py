from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Profile, User


class Command(BaseCommand):
    help = "ساخت پروفایل کاربران فاقد پروفایل، بدون تغییر پروفایل‌های موجود."

    def handle(self, *args, **options):
        repaired = 0
        missing_ids = (
            User.objects.filter(profile__isnull=True).order_by("pk").values_list("pk", flat=True)
        )
        for user_id in missing_ids.iterator(chunk_size=500):
            with transaction.atomic():
                user = User.objects.select_for_update().only("pk").filter(pk=user_id).first()
                if user is not None:
                    _, created = Profile.objects.get_or_create(user_id=user_id)
                    repaired += int(created)
        self.stdout.write(self.style.SUCCESS(f"تعداد پروفایل‌های ساخته‌شده: {repaired}"))
