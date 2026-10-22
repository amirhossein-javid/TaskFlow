from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.views import View
from django.views.generic import ListView

from .models import Notification
from .services import mark_all_notifications_read, set_notification_read


class NotificationListView(LoginRequiredMixin, ListView):
    template_name = "notifications/inbox.html"
    context_object_name = "notifications"
    paginate_by = 20
    http_method_names = ["get", "head"]

    def get_queryset(self):
        notifications = Notification.objects.visible_to(self.request.user).select_related(
            "activity__actor", "task__column__board__project__workspace"
        )
        if self.request.GET.get("unread") == "1":
            notifications = notifications.filter(read_at__isnull=True)
        return notifications

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["unread_only"] = self.request.GET.get("unread") == "1"
        return context


class NotificationStateView(LoginRequiredMixin, View):
    http_method_names = ["post"]
    read = True

    def post(self, request, *args, **kwargs):
        try:
            set_notification_read(user=request.user, notification_id=kwargs["pk"], read=self.read)
        except Notification.DoesNotExist as error:
            raise Http404("اعلان موردنظر پیدا نشد.") from error
        return redirect("notifications:inbox")


class NotificationReadAllView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        mark_all_notifications_read(user=request.user)
        return redirect("notifications:inbox")
