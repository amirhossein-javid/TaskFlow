from django import forms
from django.db.models import Q

from apps.accounts.models import User

from .models import BoardColumn, ChecklistItem, ProjectLabel, Task, TaskChecklist, TaskComment


class TaskChecklistForm(forms.ModelForm):
    class Meta:
        model = TaskChecklist
        fields = ("title",)


class ChecklistItemForm(forms.ModelForm):
    class Meta:
        model = ChecklistItem
        fields = ("text",)


class ChecklistItemStateForm(forms.Form):
    completed = forms.TypedChoiceField(
        label="وضعیت",
        choices=[("true", "انجام‌شده"), ("false", "انجام‌نشده")],
        coerce=lambda value: value == "true",
    )


class ProjectLabelForm(forms.ModelForm):
    class Meta:
        model = ProjectLabel
        fields = ("name", "color")


class TaskLabelForm(forms.Form):
    label = forms.ModelChoiceField(
        label="برچسب",
        queryset=ProjectLabel.objects.none(),
        error_messages={"invalid_choice": "برچسب انتخاب‌شده متعلق به این پروژه نیست."},
    )
    attached = forms.TypedChoiceField(
        label="عملیات",
        choices=[("true", "افزودن"), ("false", "برداشتن")],
        coerce=lambda value: value == "true",
    )

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["label"].queryset = ProjectLabel.objects.filter(project=project)


class TaskFilterForm(forms.Form):
    q = forms.CharField(
        label="جست‌وجو",
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "عنوان یا توضیحات وظیفه"}),
        error_messages={"max_length": "عبارت جست‌وجو نباید بیشتر از ۲۰۰ نویسه باشد."},
    )
    column = forms.ModelChoiceField(
        label="ستون",
        queryset=BoardColumn.objects.none(),
        required=False,
        empty_label="همهٔ ستون‌ها",
        error_messages={"invalid_choice": "ستون انتخاب‌شده معتبر نیست."},
    )
    priority = forms.ChoiceField(
        label="اولویت",
        required=False,
        choices=[("", "همهٔ اولویت‌ها"), *Task.Priority.choices],
        error_messages={"invalid_choice": "اولویت انتخاب‌شده معتبر نیست."},
    )
    assignee = forms.ChoiceField(
        label="مسئول",
        required=False,
        error_messages={"invalid_choice": "مسئول انتخاب‌شده معتبر نیست."},
    )
    due_from = forms.DateField(
        label="سررسید از",
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        error_messages={"invalid": "تاریخ شروع سررسید معتبر نیست."},
    )
    due_to = forms.DateField(
        label="سررسید تا",
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        error_messages={"invalid": "تاریخ پایان سررسید معتبر نیست."},
    )
    sort = forms.ChoiceField(
        label="مرتب‌سازی",
        required=False,
        choices=[
            ("", "ترتیب دستی"),
            ("created_desc", "جدیدترین"),
            ("created_asc", "قدیمی‌ترین"),
            ("due_asc", "نزدیک‌ترین سررسید"),
            ("due_desc", "دورترین سررسید"),
            ("priority_desc", "اولویت زیاد به کم"),
            ("priority_asc", "اولویت کم به زیاد"),
        ],
        error_messages={"invalid_choice": "مرتب‌سازی انتخاب‌شده معتبر نیست."},
    )

    def __init__(self, *args, board, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["column"].queryset = board.columns.all()
        members = workspace.memberships.values("user_id")
        assigned = Task.objects.filter(column__board=board).values("assignee_id")
        users = User.objects.filter(Q(pk__in=members) | Q(pk__in=assigned)).select_related(
            "profile"
        )
        choices = [
            ("", "همهٔ مسئول‌ها"),
            ("unassigned", "بدون مسئول"),
        ]
        for user in users:
            profile = getattr(user, "profile", None)
            label = profile.full_name if profile and profile.full_name else user.email
            choices.append((str(user.pk), label))
        self.fields["assignee"].choices = choices

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("due_from"), cleaned.get("due_to")
        if start and end and start > end:
            self.add_error("due_to", "پایان بازهٔ سررسید نباید پیش از شروع آن باشد.")
        return cleaned


class BoardColumnForm(forms.ModelForm):
    class Meta:
        model = BoardColumn
        fields = ("name",)
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "نام ستون", "autocomplete": "off"})
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("نام ستون نمی‌تواند خالی باشد.")
        return name


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ("title", "description", "priority", "due_date", "assignee")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "مثلاً طراحی صفحهٔ اصلی"}),
            "description": forms.Textarea(
                attrs={"rows": 5, "placeholder": "جزئیات و معیار انجام وظیفه"}
            ),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["assignee"].queryset = User.objects.filter(
            workspace_memberships__workspace=workspace,
            is_active=True,
        ).select_related("profile")
        self.fields["assignee"].empty_label = "بدون مسئول"
        self.fields["assignee"].error_messages["invalid_choice"] = (
            "کاربر انتخاب‌شده عضو این فضای کاری نیست."
        )

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError("عنوان وظیفه نمی‌تواند خالی باشد.")
        return title


class TaskCommentForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ("body",)
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 4,
                    "maxlength": 5000,
                    "placeholder": "دیدگاه خود را دربارهٔ این وظیفه بنویسید…",
                }
            )
        }

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("متن دیدگاه نمی‌تواند خالی باشد.")
        return body
