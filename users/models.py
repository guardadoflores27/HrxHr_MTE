from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    ROLE_LEADER     = "leader"
    ROLE_OPERATOR   = "operator"
    ROLE_ENGINEER   = "engineer"
    ROLE_SUPERVISOR = "supervisor"
    ROLE_ADMIN      = "admin"

    ROLE_CHOICES = [
        (ROLE_LEADER,     "Leader"),
        (ROLE_OPERATOR,   "Operator"),
        (ROLE_ENGINEER,   "Engineer"),
        (ROLE_SUPERVISOR, "Supervisor"),
        (ROLE_ADMIN,      "Admin"),
    ]

    ROLE_COLORS = {
        ROLE_LEADER:     ("bg-emerald-500", "Leader"),
        ROLE_OPERATOR:   ("bg-blue-500",    "Operator"),
        ROLE_ENGINEER:   ("bg-violet-500",  "Engineer"),
        ROLE_SUPERVISOR: ("bg-amber-500",   "Supervisor"),
        ROLE_ADMIN:      ("bg-rose-500",    "Admin"),
    }

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    date_of_birth = models.DateField(
        null=True, blank=True,
        help_text="Used to generate the default password (Name + birth year).",
    )

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def role_color(self):
        return self.ROLE_COLORS.get(self.role, ("bg-gray-400", self.role))[0]

    @property
    def role_label(self):
        return self.ROLE_COLORS.get(self.role, ("bg-gray-400", self.role))[1]

    # ── convenience booleans ──────────────────────────────────────────────────
    @property
    def is_leader(self):
        return self.role == self.ROLE_LEADER

    @property
    def is_operator(self):
        return self.role == self.ROLE_OPERATOR

    @property
    def is_engineer(self):
        return self.role == self.ROLE_ENGINEER

    @property
    def is_supervisor(self):
        return self.role == self.ROLE_SUPERVISOR

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    @property
    def can_view_only(self):
        """Operator & Engineer can view Daily Plans / Hourly Plans but not create/edit/delete."""
        return self.role in (self.ROLE_OPERATOR, self.ROLE_ENGINEER)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, "profile"):
        instance.profile.save()
