from django.contrib import admin

from .models import Trade, TradeScreenshot, Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "created_at")
    search_fields = ("name", "user__email")


class TradeScreenshotInline(admin.TabularInline):
    model = TradeScreenshot
    extra = 0


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ("asset", "workspace", "owner", "side", "status", "entry_datetime", "pnl_r")
    list_filter = ("status", "side", "session", "trend_direction")
    search_fields = ("asset", "setup", "owner__email")
    inlines = [TradeScreenshotInline]


@admin.register(TradeScreenshot)
class TradeScreenshotAdmin(admin.ModelAdmin):
    list_display = ("trade", "uploaded_at")
