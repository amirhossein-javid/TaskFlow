from django.urls import path

from .views import NotificationListView, NotificationReadAllView, NotificationStateView

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="inbox"),
    path("read-all/", NotificationReadAllView.as_view(), name="read_all"),
    path("<int:pk>/read/", NotificationStateView.as_view(), name="read"),
    path("<int:pk>/unread/", NotificationStateView.as_view(read=False), name="unread"),
]
