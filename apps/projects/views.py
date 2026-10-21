from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import DetailView, FormView, TemplateView, UpdateView

from apps.workspaces.mixins import WorkspaceAccessMixin, WorkspaceManagerRequiredMixin

from .forms import ProjectForm
from .mixins import ProjectAccessMixin, ProjectManagerRequiredMixin
from .models import Project
from .services import create_project, set_project_archived, update_project


class ProjectListView(WorkspaceAccessMixin, TemplateView):
    template_name = "projects/project_list.html"
    http_method_names = ["get", "head", "options"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        projects = self.workspace.projects.select_related("creator", "creator__profile")
        context["active_projects"] = projects.filter(status=Project.Status.ACTIVE)
        context["archived_projects"] = projects.filter(status=Project.Status.ARCHIVED)
        return context


class ProjectDetailView(ProjectAccessMixin, DetailView):
    template_name = "projects/project_detail.html"
    context_object_name = "project"
    http_method_names = ["get", "head", "options"]

    def get_object(self, queryset=None):
        return self.project


class ProjectCreateView(WorkspaceManagerRequiredMixin, FormView):
    template_name = "projects/project_form.html"
    form_class = ProjectForm

    def form_valid(self, form):
        project = create_project(
            workspace=self.workspace,
            actor=self.membership,
            **form.cleaned_data,
        )
        messages.success(self.request, "پروژه با موفقیت ساخته شد.")
        return redirect("projects:detail", slug=self.workspace.slug, project_id=project.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["project"] = None
        return context


class ProjectEditView(ProjectManagerRequiredMixin, UpdateView):
    template_name = "projects/project_form.html"
    form_class = ProjectForm
    context_object_name = "project"

    def get_object(self, queryset=None):
        return self.project

    def archived_response(self):
        messages.error(self.request, "برای ویرایش پروژه ابتدا آن را بازیابی کنید.")
        return redirect("projects:detail", slug=self.workspace.slug, project_id=self.project.pk)

    def get(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            self.object = update_project(
                project=self.project,
                actor=self.membership,
                **form.cleaned_data,
            )
        except ValidationError as error:
            messages.error(self.request, error.messages[0])
            return redirect("projects:detail", slug=self.workspace.slug, project_id=self.project.pk)
        messages.success(self.request, "پروژه با موفقیت به‌روزرسانی شد.")
        return redirect("projects:detail", slug=self.workspace.slug, project_id=self.object.pk)


class ProjectArchiveView(ProjectManagerRequiredMixin, View):
    template_name = "projects/project_archive_confirm.html"
    http_method_names = ["get", "post", "head", "options"]

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            {
                "workspace": self.workspace,
                "membership": self.membership,
                "project": self.project,
            },
        )

    def post(self, request, *args, **kwargs):
        set_project_archived(project=self.project, actor=self.membership, archived=True)
        messages.success(request, "پروژه بایگانی شد.")
        return redirect("projects:detail", slug=self.workspace.slug, project_id=self.project.pk)


class ProjectRestoreView(ProjectManagerRequiredMixin, View):
    http_method_names = ["post", "options"]

    def post(self, request, *args, **kwargs):
        set_project_archived(project=self.project, actor=self.membership, archived=False)
        messages.success(request, "پروژه بازیابی شد.")
        return redirect("projects:detail", slug=self.workspace.slug, project_id=self.project.pk)
