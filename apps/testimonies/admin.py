from django.contrib import admin

from .models import (
    Reaction,
    ReactionChangeLog,
    Testimony,
    TestimonyCategory,
    TestimonyComment,
    TestimonyFavorite,
    TestimonyReaction,
    TestimonyWatch,
    UserFollowedCategory,
)


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


@admin.register(TestimonyComment)
class TestimonyCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "testimony", "author", "created_at")
    search_fields = ("author__email", "testimony__title", "body")


@admin.register(TestimonyReaction)
class TestimonyReactionAdmin(admin.ModelAdmin):
    list_display = ("user", "testimony", "reaction", "created_at")
    list_filter = ("reaction",)
    search_fields = ("user__email", "testimony__title")


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    # Read-mostly here; the dashboard's Reactions page is where they're managed.
    list_display = ("label", "key", "icon", "is_active", "default_position")
    list_filter = ("is_active",)
    readonly_fields = ("key",)


@admin.register(ReactionChangeLog)
class ReactionChangeLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "summary")
    list_filter = ("action",)

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(TestimonyWatch)
class TestimonyWatchAdmin(admin.ModelAdmin):
    list_display = ("user", "testimony", "created_at")
    search_fields = ("user__email", "testimony__title")


@admin.register(UserFollowedCategory)
class UserFollowedCategoryAdmin(admin.ModelAdmin):
    list_display = ("user", "category", "created_at")
    search_fields = ("user__email", "category__name")
