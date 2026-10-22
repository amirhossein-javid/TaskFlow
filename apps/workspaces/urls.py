from django.urls import path

from .views import (
    ChangeRoleView,
    InvitationDetailView,
    InviteMemberView,
    MemberListView,
    RemoveMemberView,
    WorkspaceCreateView,
    WorkspaceDeleteView,
    WorkspaceDetailView,
    WorkspaceLeaveView,
    WorkspaceListView,
    WorkspaceSettingsView,
)

app_name = "workspaces"

urlpatterns = [
    path("", WorkspaceListView.as_view(), name="list"),
    path("new/", WorkspaceCreateView.as_view(), name="create"),
    path("invitations/<str:token>/", InvitationDetailView.as_view(), name="invitation"),
    path("<slug:slug>/", WorkspaceDetailView.as_view(), name="detail"),
    path("<slug:slug>/members/", MemberListView.as_view(), name="members"),
    path("<slug:slug>/members/invite/", InviteMemberView.as_view(), name="invite"),
    path(
        "<slug:slug>/members/<int:membership_id>/role/",
        ChangeRoleView.as_view(),
        name="change_role",
    ),
    path(
        "<slug:slug>/members/<int:membership_id>/remove/",
        RemoveMemberView.as_view(),
        name="remove_member",
    ),
    path("<slug:slug>/settings/", WorkspaceSettingsView.as_view(), name="settings"),
    path("<slug:slug>/leave/", WorkspaceLeaveView.as_view(), name="leave"),
    path("<slug:slug>/delete/", WorkspaceDeleteView.as_view(), name="delete"),
]
