from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.contrib.auth.forms import UserCreationForm as DjangoUserCreationForm

from .models import Profile, User


class PersianUserCreationForm(DjangoUserCreationForm):
    password1 = forms.CharField(
        label="رمز عبور",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label="تکرار رمز عبور",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    error_messages = {"password_mismatch": "رمزهای عبور یکسان نیستند."}


class UserCreationForm(PersianUserCreationForm):
    class Meta(DjangoUserCreationForm.Meta):
        model = User
        fields = ("email",)


class RegistrationForm(PersianUserCreationForm):
    email = forms.EmailField(
        label="ایمیل",
        error_messages={
            "required": "وارد کردن ایمیل الزامی است.",
            "invalid": "یک ایمیل معتبر وارد کنید.",
        },
    )
    full_name = forms.CharField(
        label="نام کامل",
        max_length=255,
        error_messages={"required": "وارد کردن نام کامل الزامی است."},
    )

    class Meta(DjangoUserCreationForm.Meta):
        model = User
        fields = ("email", "full_name")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("کاربری با این ایمیل وجود دارد.")
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            profile = user.profile
            profile.full_name = self.cleaned_data["full_name"].strip()
            profile.save(update_fields=["full_name"])
        return user


class ProfileForm(forms.ModelForm):
    max_avatar_size = 2 * 1024 * 1024
    allowed_avatar_types = {"image/jpeg", "image/png", "image/webp"}

    class Meta:
        model = Profile
        fields = ("full_name", "bio", "avatar")
        widgets = {"bio": forms.Textarea(attrs={"rows": 5})}

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar or not hasattr(avatar, "content_type"):
            return avatar
        if avatar.size > self.max_avatar_size:
            raise forms.ValidationError("حجم تصویر پروفایل نباید بیشتر از ۲ مگابایت باشد.")
        if avatar.content_type not in self.allowed_avatar_types:
            raise forms.ValidationError("فرمت تصویر باید JPEG، PNG یا WebP باشد.")
        return avatar


class UserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField(
        label="رمز عبور",
        help_text=(
            "رمزهای عبور به‌صورت امن ذخیره می‌شوند و قابل مشاهده نیستند. "
            "برای تغییر رمز از فرم تغییر رمز عبور در مدیریت استفاده کنید."
        ),
    )

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
        )
