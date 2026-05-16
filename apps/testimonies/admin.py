from django.contrib import admin

from .models import Testimony, TestimonyCategory, TestimonyFavorite


@admin.register(TestimonyCategory)
class TestimonyCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")


@admin.register(Testimony)
class TestimonyAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "category", "testimony_type", "status", "created_at")
    list_filter = ("status", "testimony_type", "category")
    search_fields = ("title", "body", "author__email")


@admin.register(TestimonyFavorite)
class TestimonyFavoriteAdmin(admin.ModelAdmin):
    list_display = ("user", "testimony", "created_at")
    search_fields = ("user__email", "testimony__title")
