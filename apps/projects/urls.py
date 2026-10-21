from django.urls import path

from .views import (
    ProjectArchiveView,
    ProjectCreateView,
    ProjectDetailView,
    ProjectEditView,
    ProjectListView,
    ProjectRestoreView,
)

app_name = "projects"

urlpatterns = [
    path("", ProjectListView.as_view(), name="list"),
    path("new/", ProjectCreateView.as_view(), name="create"),
    path("<int:project_id>/", ProjectDetailView.as_view(), name="detail"),
    path("<int:project_id>/edit/", ProjectEditView.as_view(), name="edit"),
    path("<int:project_id>/archive/", ProjectArchiveView.as_view(), name="archive"),
    path("<int:project_id>/restore/", ProjectRestoreView.as_view(), name="restore"),
]
