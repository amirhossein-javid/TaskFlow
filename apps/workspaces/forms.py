from django import forms

from apps.accounts.models import User

from .models import Workspace, WorkspaceMembership


class WorkspaceForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ("name", "slug")
        labels = {"name": "نام فضای کاری", "slug": "شناسهٔ فضای کاری"}
        help_texts = {"slug": "فقط حروف کوچک انگلیسی، عدد و خط تیره؛ برای نمونه: product-team"}
        error_messages = {
            "name": {"required": "نام فضای کاری را وارد کنید."},
            "slug": {
                "required": "شناسهٔ فضای کاری را وارد کنید.",
                "invalid": "شناسه فقط می‌تواند شامل حروف انگلیسی، عدد و خط تیره باشد.",
                "unique": "این شناسه قبلاً استفاده شده است.",
            },
        }

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_slug(self):
        slug = self.cleaned_data["slug"].strip().lower()
        queryset = Workspace.objects.filter(slug__iexact=slug)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("این شناسه قبلاً استفاده شده است.")
        return slug


class InvitationForm(forms.Form):
    email = forms.EmailField(
        label="ایمیل عضو جدید",
        error_messages={
            "required": "ایمیل را وارد کنید.",
            "invalid": "یک ایمیل معتبر وارد کنید.",
        },
    )
    role = forms.ChoiceField(label="نقش")

    def __init__(self, *args, actor_membership: WorkspaceMembership, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(WorkspaceMembership.Role.MEMBER, "عضو")]
        if actor_membership.role == WorkspaceMembership.Role.OWNER:
            choices.insert(0, (WorkspaceMembership.Role.ADMIN, "مدیر"))
        self.fields["role"].choices = choices

    def clean_email(self):
        return User.objects.normalize_email(self.cleaned_data["email"]).lower()


class MembershipRoleForm(forms.Form):
    role = forms.ChoiceField(
        label="نقش",
        choices=[
            (WorkspaceMembership.Role.OWNER, "مالک"),
            (WorkspaceMembership.Role.ADMIN, "مدیر"),
            (WorkspaceMembership.Role.MEMBER, "عضو"),
        ],
    )


class WorkspaceDeleteForm(forms.Form):
    confirmation = forms.CharField(label="نام فضای کاری")

    def __init__(self, *args, workspace: Workspace, **kwargs):
        self.workspace = workspace
        super().__init__(*args, **kwargs)

    def clean_confirmation(self):
        value = self.cleaned_data["confirmation"].strip()
        if value != self.workspace.name:
            raise forms.ValidationError("نام واردشده با نام فضای کاری یکسان نیست.")
        return value
