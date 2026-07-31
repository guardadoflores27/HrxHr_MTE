# users/admin.py
# ─────────────────────────────────────────────────────────────────────────────
# Inlines UserProfile.role directly onto Django's User admin, so role is edited
# alongside the account instead of on a separate, disconnected page. The role
# column and filter are surfaced on the user changelist.
# ─────────────────────────────────────────────────────────────────────────────

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"
    fields = ("role",)


class UserAdmin(DjangoUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ("username", "email", "first_name", "last_name",
                    "role_display", "is_active", "is_staff")
    list_filter  = DjangoUserAdmin.list_filter + ("profile__role",)
    list_select_related = ("profile",)

    @admin.display(description="Role", ordering="profile__role")
    def role_display(self, obj):
        prof = getattr(obj, "profile", None)
        return prof.get_role_display() if prof else "—"


# Swap Django's default User admin for our profile-aware one.
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# Keep UserProfile independently searchable (needed for autocomplete elsewhere).
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display        = ("user", "role")
    list_filter         = ("role",)
    search_fields       = ("user__username", "user__first_name", "user__last_name")
    list_select_related = ("user",)
    ordering            = ("user__username",)
