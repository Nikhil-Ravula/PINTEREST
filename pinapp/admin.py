from django.contrib import admin

from .models import SentProduct


@admin.register(SentProduct)
class SentProductAdmin(admin.ModelAdmin):
    list_display = ("asin", "title", "topic", "sent_at")
    list_filter = ("sent_at",)
    search_fields = ("asin", "title", "topic")
    readonly_fields = ("sent_at",)
