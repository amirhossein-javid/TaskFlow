from django import forms

from apps.accounts.models import User

from .models import BoardColumn, Task


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
