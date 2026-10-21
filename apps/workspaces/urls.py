from django.urls import path

from . import views

app_name = "workspaces"

urlpatterns = [
    path("", views.workspace_list, name="list"),
    path("new/", views.workspace_create, name="create"),
    path("invitations/<str:token>/", views.invitation_detail, name="invitation"),
    path("<slug:slug>/", views.workspace_detail, name="detail"),
    path("<slug:slug>/members/", views.member_list, name="members"),
    path("<slug:slug>/members/invite/", views.invite_member, name="invite"),
    path(
        "<slug:slug>/members/<int:membership_id>/role/",
        views.change_role,
        name="change_role",
    ),
    path(
        "<slug:slug>/members/<int:membership_id>/remove/",
        views.remove_member,
        name="remove_member",
    ),
    path("<slug:slug>/settings/", views.workspace_settings, name="settings"),
    path("<slug:slug>/leave/", views.workspace_leave, name="leave"),
    path("<slug:slug>/delete/", views.workspace_delete, name="delete"),
]
