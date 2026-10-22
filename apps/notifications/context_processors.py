from .models import Notification


def notification_navigation(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "notification_unread_count": Notification.objects.visible_to(request.user)
        .filter(read_at__isnull=True)
        .count(),
    }
