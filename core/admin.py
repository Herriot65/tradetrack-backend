from django.contrib import admin

from .models import Asset, EmotionTag, Journal, MistakeTag, SetupTag, Trade, TradeScreenshot


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "journal_type", "currency", "created_at")
    list_filter = ("journal_type", "currency")
    search_fields = ("name", "user__email")


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name", "journal", "is_archived")
    list_filter = ("is_archived",)
    search_fields = ("symbol", "name")


@admin.register(EmotionTag)
class EmotionTagAdmin(admin.ModelAdmin):
    list_display = ("label", "journal", "is_archived")
    list_filter = ("is_archived",)
    search_fields = ("label",)


@admin.register(MistakeTag)
class MistakeTagAdmin(admin.ModelAdmin):
    list_display = ("label", "journal", "is_archived")
    list_filter = ("is_archived",)
    search_fields = ("label",)


@admin.register(SetupTag)
class SetupTagAdmin(admin.ModelAdmin):
    list_display = ("label", "journal", "is_archived")
    list_filter = ("is_archived",)
    search_fields = ("label",)


class TradeScreenshotInline(admin.TabularInline):
    model = TradeScreenshot
    extra = 0


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ("asset", "journal", "side", "status", "entry_datetime", "pnl_r")
    list_filter = ("status", "side", "session", "trend_direction")
    search_fields = ("asset__symbol", "notes")
    inlines = [TradeScreenshotInline]


@admin.register(TradeScreenshot)
class TradeScreenshotAdmin(admin.ModelAdmin):
    list_display = ("trade", "uploaded_at")
