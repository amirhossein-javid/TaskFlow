from django.conf import settings
from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, raw, using, **kwargs):
    if created and not raw:
        Profile.objects.using(using).get_or_create(user=instance)


@receiver(pre_delete, sender=Profile)
def protect_profile_deletion(sender, instance, origin, **kwargs):
    if isinstance(origin, Profile) or getattr(origin, "model", None) is Profile:
        raise ProtectedError("پروفایل فقط همراه با حذف حساب کاربری حذف می‌شود.", [instance])
