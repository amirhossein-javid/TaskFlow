from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image, PngImagePlugin

from apps.accounts.forms import ProfileForm
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def upload(image_format="PNG", name="payload.png", size=(24, 24), animated=False):
    stream = BytesIO()
    image = Image.new("RGB", size, "red")
    options = {}
    if image_format == "PNG":
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("private", "discard this metadata")
        options["pnginfo"] = metadata
    if animated:
        options.update(save_all=True, append_images=[Image.new("RGB", size, "blue")], duration=100)
    image.save(stream, format=image_format, **options)
    return SimpleUploadedFile(name, stream.getvalue() + b"<script>payload</script>", "image/png")


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_avatar_reencodes_pixels_and_discards_filename_metadata_and_appended_payload(image_format):
    form = ProfileForm(data={"full_name": "نام", "bio": ""}, files={"avatar": upload(image_format)})
    assert form.is_valid(), form.errors
    avatar = form.cleaned_data["avatar"]
    assert len(avatar.name) == 36 and avatar.name.endswith(".png")
    assert avatar.content_type == "image/png"
    assert b"<script>" not in avatar.read()
    avatar.seek(0)
    with Image.open(avatar) as image:
        assert image.format == "PNG"
        assert image.size == (24, 24)
        assert not image.info


@pytest.mark.parametrize(
    "avatar",
    [
        lambda: upload("GIF"),
        lambda: upload(name="payload.html"),
        lambda: upload("WEBP", animated=True),
        lambda: SimpleUploadedFile("image.png", b"<svg onload='alert(1)'/>", "image/png"),
        lambda: upload(size=(4097, 4096)),
    ],
)
def test_avatar_rejects_spoofed_animated_invalid_or_excessive_images(avatar):
    form = ProfileForm(data={"full_name": "نام", "bio": ""}, files={"avatar": avatar()})
    assert not form.is_valid()
    assert "avatar" in form.errors


def test_avatar_rejects_oversized_normalized_output():
    with patch.object(ProfileForm, "max_avatar_size", 300):
        # A compact palette PNG grows when normalized to RGB pixels.
        image = Image.new("P", (128, 128))
        image.putpalette([255, 0, 0, 0, 0, 255] + [0] * 762)
        image.putdata([(x + y) % 2 for y in range(128) for x in range(128)])
        stream = BytesIO()
        image.save(stream, format="PNG", bits=1)
        data = stream.getvalue()
        form = ProfileForm(
            data={"full_name": "نام", "bio": ""},
            files={"avatar": SimpleUploadedFile("small.png", data, "image/png")},
        )
        assert len(data) < 300
        assert not form.is_valid()
        assert "avatar" in form.errors


def test_avatar_preserves_transparency_and_display_orientation():
    for image in (Image.new("P", (3, 2)), Image.new("RGB", (3, 2), "red")):
        stream = BytesIO()
        if image.mode == "P":
            image.info["transparency"] = 0
            image.save(stream, format="PNG")
            expected_mode, expected_size = "RGBA", (3, 2)
        else:
            exif = Image.Exif()
            exif[274] = 6
            image.save(stream, format="JPEG", exif=exif)
            expected_mode, expected_size = "RGB", (2, 3)
        form = ProfileForm(
            data={"full_name": "نام", "bio": ""},
            files={"avatar": SimpleUploadedFile("image.png", stream.getvalue(), "image/png")},
        )
        assert form.is_valid(), form.errors
        with Image.open(form.cleaned_data["avatar"]) as normalized:
            assert normalized.mode == expected_mode
            assert normalized.size == expected_size
            assert not normalized.getexif()
            if expected_mode == "RGBA":
                assert normalized.getpixel((0, 0))[3] == 0


def test_profile_admin_uses_the_same_safe_upload_and_preserves_existing_file(client, tmp_path):
    admin = User.objects.create_superuser("admin@example.com", "SecurePass123!")
    client.force_login(admin)
    url = reverse("admin:accounts_profile_change", args=[admin.profile.pk])
    with override_settings(MEDIA_ROOT=tmp_path):
        response = client.post(url, {"full_name": "نام", "bio": "", "avatar": upload()})
        assert response.status_code == 302
        admin.profile.refresh_from_db()
        filename = admin.profile.avatar.name
        assert filename.endswith(".png") and "payload" not in filename
        assert client.post(url, {"full_name": "نام تازه", "bio": ""}).status_code == 302
        admin.profile.refresh_from_db()
        assert admin.profile.avatar.name == filename
        response = client.post(url, {"full_name": "نام", "bio": "", "avatar": upload("GIF")})
        assert response.status_code == 200
        assert "avatar" in response.context["adminform"].form.errors
        assert (
            client.post(url, {"full_name": "نام", "bio": "", "avatar-clear": "on"}).status_code
            == 302
        )
        admin.profile.refresh_from_db()
        assert not admin.profile.avatar
