from django import forms

from .models import Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ("name", "description")
        labels = {"name": "نام پروژه", "description": "توضیحات"}
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 6, "placeholder": "هدف و محدودهٔ پروژه را بنویسید."}
            )
        }
        error_messages = {
            "name": {
                "required": "نام پروژه را وارد کنید.",
                "max_length": "نام پروژه بیش از حد طولانی است.",
            }
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("نام پروژه نمی‌تواند خالی باشد.")
        return name

    def clean_description(self):
        return self.cleaned_data["description"].strip()
