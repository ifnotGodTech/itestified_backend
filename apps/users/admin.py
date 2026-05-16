from django.contrib import admin

from .models import AdminAssignment, AdminRole, Profile, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "account_status", "is_staff", "is_superuser")
    search_fields = ("email",)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "full_name", "phone_number")
    search_fields = ("user__email", "full_name")


@admin.register(AdminRole)
class AdminRoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(AdminAssignment)
class AdminAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "status", "activated_at", "deactivated_at")
    search_fields = ("user__email", "role__code", "role__name")
