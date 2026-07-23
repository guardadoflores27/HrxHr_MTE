"""Role permission matrix tests.

Locks in the matrix documented in users/decorators.py:

  Section        | Leader | Operator | Engineer | Admin
  Daily Plans    | full   | view     | view     | full
  Work Centers   | view   | view     | full     | full
  Subprocesses   | view   | view     | full     | full
  Shifts         | view   | view     | full     | full
  Users Admin    | view   | view     | view     | full

These tests exercise real HTTP requests and assert against the DATABASE, so a
regression in either the view guards or the templates is caught.
"""
import datetime as dt

from django.test import TestCase, Client
from django.contrib.auth.models import User

from users.models import UserProfile
from core.models import WorkCenter, SubProcess, SubProcessType, Shift
from planning.models import DailyPlan

ROLES = ["leader", "operator", "engineer", "admin"]


class RolePermissionMatrixTestCase(TestCase):

    def setUp(self):
        self.users = {}
        for role in ROLES:
            u = User.objects.create_user(f"u_{role}", password="pw")
            # update() bypasses the post_save signal that would reset the role.
            UserProfile.objects.filter(user=u).update(role=role)
            self.users[role] = User.objects.get(pk=u.pk)

        self.wc = WorkCenter.objects.create(name="WC-ROLE")
        spt = SubProcessType.objects.create(
            name="T-ROLE", applies_to="reactores", units_per_piece=1)
        self.sp = SubProcess.objects.create(
            work_center=self.wc, name="SP-ROLE", subprocess_type=spt)
        self.shift = Shift.objects.create(
            name="ROLE", code="RL",
            start_time=dt.time(6), end_time=dt.time(14), is_active=True)

    def _client(self, role):
        c = Client()
        c.force_login(self.users[role])
        return c

    def _make_plan(self):
        return DailyPlan.objects.create(
            date=dt.date(2026, 9, 20), work_center=self.wc,
            subprocess=self.sp, headcount=5, shift=self.shift)

    # ── Roles are what we think they are ─────────────────────────────────
    def test_roles_are_set_correctly(self):
        for role in ROLES:
            self.assertEqual(self.users[role].profile.role, role)

    # ── Daily Plans: Leader + Admin may write, others may not ────────────
    def test_only_leader_and_admin_can_delete_plans(self):
        for role in ROLES:
            plan = self._make_plan()
            self._client(role).post(f"/plans/{plan.id}/delete/")
            deleted = not DailyPlan.objects.filter(id=plan.id).exists()
            self.assertEqual(
                deleted, role in ("leader", "admin"),
                f"{role} delete permission is wrong")
            DailyPlan.objects.filter(id=plan.id).delete()

    def test_only_leader_and_admin_can_open_plan_create(self):
        for role in ROLES:
            r = self._client(role).get("/plans/new/")
            allowed = r.status_code == 200
            self.assertEqual(
                allowed, role in ("leader", "admin"),
                f"{role} create-page access is wrong")

    # ── Catalogs: Engineer + Admin only (this was a real security hole) ──
    def test_only_engineer_and_admin_can_create_work_centers(self):
        for role in ROLES:
            name = f"WC_NEW_{role}"
            self._client(role).post(
                "/core/workcenters/new/", {"name": name, "is_active": "on"})
            created = WorkCenter.objects.filter(name=name).exists()
            self.assertEqual(
                created, role in ("engineer", "admin"),
                f"{role} must not be able to create a Work Center")
            WorkCenter.objects.filter(name=name).delete()

    def test_only_engineer_and_admin_can_create_subprocesses(self):
        for role in ROLES:
            r = self._client(role).get("/core/subprocesses/new/")
            allowed = r.status_code == 200
            self.assertEqual(
                allowed, role in ("engineer", "admin"),
                f"{role} subprocess write access is wrong")

    def test_only_engineer_and_admin_can_manage_shifts(self):
        for role in ROLES:
            r = self._client(role).get("/core/shifts/new/")
            allowed = r.status_code == 200
            self.assertEqual(
                allowed, role in ("engineer", "admin"),
                f"{role} shift management access is wrong")

    # ── User administration: Admin only for writes ───────────────────────
    def test_only_admin_can_create_users(self):
        for role in ROLES:
            r = self._client(role).get("/users/admin/users/create/")
            allowed = r.status_code == 200
            self.assertEqual(
                allowed, role == "admin",
                f"{role} must not reach the user-create page")

    def test_everyone_can_view_user_list(self):
        for role in ROLES:
            r = self._client(role).get("/users/admin/users/")
            self.assertEqual(r.status_code, 200, f"{role} should view users")

    # ── Buttons match permissions (no dead-end clicks) ───────────────────
    def test_new_plan_button_disabled_for_view_only_roles(self):
        for role in ROLES:
            html = self._client(role).get("/plans/").content.decode()
            disabled = "cursor-not-allowed select-none" in html
            self.assertEqual(
                disabled, role in ("operator", "engineer"),
                f"{role} should{'' if role in ('operator','engineer') else ' not'} "
                f"see a disabled New Plan button")

    # ── The phantom "supervisor" role must never come back ───────────────
    def test_no_phantom_supervisor_role(self):
        valid = {r for r, _ in UserProfile.ROLE_CHOICES}
        self.assertEqual(valid, {"leader", "operator", "engineer", "admin"})
        self.assertNotIn("supervisor", valid)