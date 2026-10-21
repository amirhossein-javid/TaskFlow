from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("وارد کردن ایمیل الزامی است.")

        user = self.model(
            email=self.normalize_email(email).lower(),
            **extra_fields,
        )
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("مدیر سیستم باید دسترسی ورود به بخش مدیریت را داشته باشد.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("مدیر سیستم باید همهٔ مجوزها را داشته باشد.")
        if not password:
            raise ValueError("وارد کردن رمز عبور مدیر سیستم الزامی است.")

        return self.create_user(email, password, **extra_fields)
