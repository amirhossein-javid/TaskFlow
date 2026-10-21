from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.workspaces.permissions import get_workspace_membership, require_manager

from .forms import ProjectForm
from .models import Project
from .permissions import get_project_for_member
from .services import create_project, set_project_archived, update_project


@login_required
def project_list(request, slug):
    workspace, membership = get_workspace_membership(user=request.user, slug=slug)
    projects = workspace.projects.select_related("creator", "creator__profile")
    return render(
        request,
        "projects/project_list.html",
        {
            "workspace": workspace,
            "membership": membership,
            "active_projects": projects.filter(status=Project.Status.ACTIVE),
            "archived_projects": projects.filter(status=Project.Status.ARCHIVED),
        },
    )


@login_required
def project_detail(request, slug, project_id):
    workspace, membership, project = get_project_for_member(
        user=request.user, slug=slug, project_id=project_id
    )
    return render(
        request,
        "projects/project_detail.html",
        {"workspace": workspace, "membership": membership, "project": project},
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_create(request, slug):
    workspace, membership = get_workspace_membership(user=request.user, slug=slug)
    require_manager(membership)
    form = ProjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        project = create_project(
            workspace=workspace,
            actor=membership,
            **form.cleaned_data,
        )
        messages.success(request, "پروژه با موفقیت ساخته شد.")
        return redirect("projects:detail", slug=workspace.slug, project_id=project.pk)
    return render(
        request,
        "projects/project_form.html",
        {"workspace": workspace, "membership": membership, "form": form, "project": None},
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_edit(request, slug, project_id):
    workspace, membership, project = get_project_for_member(
        user=request.user, slug=slug, project_id=project_id
    )
    require_manager(membership)
    if project.status == Project.Status.ARCHIVED:
        messages.error(request, "برای ویرایش پروژه ابتدا آن را بازیابی کنید.")
        return redirect("projects:detail", slug=workspace.slug, project_id=project.pk)
    form = ProjectForm(request.POST or None, instance=project)
    if request.method == "POST" and form.is_valid():
        try:
            project = update_project(project=project, actor=membership, **form.cleaned_data)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect("projects:detail", slug=workspace.slug, project_id=project.pk)
        messages.success(request, "پروژه با موفقیت به‌روزرسانی شد.")
        return redirect("projects:detail", slug=workspace.slug, project_id=project.pk)
    return render(
        request,
        "projects/project_form.html",
        {"workspace": workspace, "membership": membership, "form": form, "project": project},
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_archive(request, slug, project_id):
    workspace, membership, project = get_project_for_member(
        user=request.user, slug=slug, project_id=project_id
    )
    require_manager(membership)
    if request.method == "POST":
        set_project_archived(project=project, actor=membership, archived=True)
        messages.success(request, "پروژه بایگانی شد.")
        return redirect("projects:detail", slug=workspace.slug, project_id=project.pk)
    return render(
        request,
        "projects/project_archive_confirm.html",
        {"workspace": workspace, "membership": membership, "project": project},
    )


@login_required
@require_POST
def project_restore(request, slug, project_id):
    workspace, membership, project = get_project_for_member(
        user=request.user, slug=slug, project_id=project_id
    )
    require_manager(membership)
    set_project_archived(project=project, actor=membership, archived=False)
    messages.success(request, "پروژه بازیابی شد.")
    return redirect("projects:detail", slug=workspace.slug, project_id=project.pk)
