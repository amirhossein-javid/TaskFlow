from django.contrib import admin

from .models import Board, BoardColumn


class BoardColumnInline(admin.TabularInline):
    model = BoardColumn
    extra = 0
    ordering = ("position",)


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ("project", "created_at")
    search_fields = ("project__name", "project__workspace__name")
    inlines = (BoardColumnInline,)
