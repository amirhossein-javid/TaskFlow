from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import FormView, UpdateView

from .db import is_email_conflict
from .forms import ProfileForm, RegistrationForm
from .models import Profile


class RegistrationView(FormView):
    template_name = "accounts/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("accounts:login")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(self.get_next_url() or "accounts:profile")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError as error:
            if not is_email_conflict(error):
                raise
            form.add_error("email", "کاربری با این ایمیل وجود دارد.")
            return self.form_invalid(form)
        messages.success(self.request, "حساب کاربری شما ساخته شد. اکنون وارد شوید.")
        return super().form_valid(form)

    def get_next_url(self):
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["next"] = self.get_next_url()
        return context

    def get_success_url(self):
        next_url = self.get_next_url()
        if next_url:
            query = urlencode({"next": next_url}, safe="/")
            return f"{reverse('accounts:login')}?{query}"
        return str(self.success_url)


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = Profile
    form_class = ProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user.profile

    def form_valid(self, form):
        messages.success(self.request, "پروفایل شما با موفقیت به‌روزرسانی شد.")
        return super().form_valid(form)
