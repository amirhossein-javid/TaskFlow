import warnings
from io import BytesIO
from uuid import uuid4

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.contrib.auth.forms import UserCreationForm as DjangoUserCreationForm
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import Profile, User


class EmailIdentityFormMixin:
    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        users = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            users = users.exclude(pk=self.instance.pk)
        if users.exists():
            raise forms.ValidationError("کاربری با این ایمیل وجود دارد.")
        return email


class PersianUserCreationForm(EmailIdentityFormMixin, DjangoUserCreationForm):
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
    max_avatar_pixels = 4096 * 4096

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
        try:
            avatar.seek(0)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(avatar) as image:
                    if image.format not in {"JPEG", "PNG", "WEBP"}:
                        raise forms.ValidationError("فرمت تصویر باید JPEG، PNG یا WebP باشد.")
                    if image.width * image.height > self.max_avatar_pixels:
                        raise forms.ValidationError("ابعاد تصویر پروفایل بیش از حد مجاز است.")
                    if getattr(image, "n_frames", 1) != 1:
                        raise forms.ValidationError("تصویر پروفایل نباید متحرک باشد.")
                    image.load()
                    image = ImageOps.exif_transpose(image)
                    # Re-encode pixels only: discard metadata, appended payloads and filenames.
                    mode = (
                        "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
                    )
                    pixels = Image.new(mode, image.size)
                    pixels.paste(image.convert(mode))
                    output = BytesIO()
                    pixels.save(output, format="PNG")
        except (
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as error:
            raise forms.ValidationError("تصویر پروفایل معتبر نیست.") from error
        if output.tell() > self.max_avatar_size:
            raise forms.ValidationError("حجم تصویر پروفایل نباید بیشتر از ۲ مگابایت باشد.")
        return SimpleUploadedFile(f"{uuid4().hex}.png", output.getvalue(), content_type="image/png")


class ProfileAdminForm(ProfileForm):
    class Meta(ProfileForm.Meta):
        fields = ("user", "full_name", "bio", "avatar")


class UserChangeForm(EmailIdentityFormMixin, forms.ModelForm):
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
