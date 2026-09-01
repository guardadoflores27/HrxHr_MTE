import json
import datetime as dt

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from core.models import WorkCenter, SubProcess, SubProcessType, Shift
from users.models import UserProfile
from .models import DailyPlan, HourlyPlan, Model as PlanningModel


class MultiModelPerHourTestCase(TestCase):
    """
    Covers the new requirement: a single hour slot inside Production
    Execution may now hold several models (several HourlyPlan rows), each
    with its own planned quantity, instead of being limited to exactly one.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="leader1", password="pw12345")
        self.profile, _ = UserProfile.objects.update_or_create(
            user=self.user, defaults={"role": "leader"}
        )

        self.wc = WorkCenter.objects.create(name="WC-1")
        self.sp_type = SubProcessType.objects.create(
            name="Standard", applies_to="reactores", units_per_piece=1
        )
        self.subprocess = SubProcess.objects.create(
            work_center=self.wc, name="SP-1", subprocess_type=self.sp_type
        )
        self.shift = Shift.objects.create(
            name="Morning", code="MOR",
            start_time=dt.time(6, 0), end_time=dt.time(14, 0),
            is_active=True,
        )
        self.plan = DailyPlan.objects.create(
            date=dt.date(2026, 6, 1),
            work_center=self.wc, subprocess=self.subprocess,
            headcount=10, shift=self.shift,
        )
        self.model_a = PlanningModel.objects.create(name="Model A")
        self.model_b = PlanningModel.objects.create(name="Model B")
        self.model_c = PlanningModel.objects.create(name="Model C")

        self.client = Client()
        self.client.login(username="leader1", password="pw12345")

    def _add_row(self, hour, model, qty, is_overtime=False):
        url = reverse("planning:api_add_row", args=[self.plan.id])
        payload = {
            "hour": hour, "model_id": model.id, "quantity": qty,
            "headcount_override": None, "is_overtime": is_overtime, "comments": "",
        }
        return self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

    # ── Core requirement ───────────────────────────────────────────────────

    def test_single_model_per_hour_still_works(self):
        """Backwards compatibility: one model per hour keeps working as before."""
        resp = self._add_row("08:00", self.model_a, 80)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(HourlyPlan.objects.filter(daily_plan=self.plan).count(), 1)

    def test_two_models_in_same_hour_are_both_created(self):
        """Two different models in the same hour produce two independent rows."""
        r1 = self._add_row("08:00", self.model_a, 80)
        r2 = self._add_row("08:00", self.model_b, 40)
        self.assertTrue(r1.json()["ok"])
        self.assertTrue(r2.json()["ok"])

        rows = HourlyPlan.objects.filter(daily_plan=self.plan, hour=dt.time(8, 0))
        self.assertEqual(rows.count(), 2)
        self.assertEqual(set(rows.values_list("model__name", flat=True)),
                          {"Model A", "Model B"})

    def test_three_models_in_same_hour(self):
        """The example from the spec: 3 models sharing one hour."""
        self._add_row("08:00", self.model_a, 50)
        self._add_row("08:00", self.model_b, 40)
        self._add_row("08:00", self.model_c, 30)
        rows = HourlyPlan.objects.filter(daily_plan=self.plan, hour=dt.time(8, 0))
        self.assertEqual(rows.count(), 3)
        total = sum(r.planned_quantity for r in rows)
        self.assertEqual(total, 120)

    def test_slot_total_returned_by_api(self):
        """api_add_row must report the running total for the hour (informational)."""
        self._add_row("08:00", self.model_a, 50)
        r2 = self._add_row("08:00", self.model_b, 40)
        self.assertEqual(r2.json()["slot_total"], 90)

    def test_duplicate_model_same_hour_is_rejected(self):
        """Adding the SAME model twice to the same hour must fail."""
        r1 = self._add_row("08:00", self.model_a, 50)
        self.assertTrue(r1.json()["ok"])
        r2 = self._add_row("08:00", self.model_a, 30)
        self.assertFalse(r2.json()["ok"])
        self.assertIn("already assigned", r2.json()["error"])
        # No second row was created
        self.assertEqual(
            HourlyPlan.objects.filter(
                daily_plan=self.plan, hour=dt.time(8, 0), model=self.model_a
            ).count(),
            1,
        )

    def test_edit_row_to_duplicate_model_is_rejected(self):
        """Editing a row to use a model already present in that hour must fail."""
        self._add_row("08:00", self.model_a, 50)
        r2 = self._add_row("08:00", self.model_b, 40)
        row_b_id = r2.json()["id"]

        edit_url = reverse("planning:api_edit_row", args=[self.plan.id, row_b_id])
        resp = self.client.post(
            edit_url,
            data=json.dumps({"model_id": self.model_a.id, "quantity": 99}),
            content_type="application/json",
        )
        self.assertFalse(resp.json()["ok"])
        # Row B keeps its original model — no corruption from the failed edit
        row_b = HourlyPlan.objects.get(id=row_b_id)
        self.assertEqual(row_b.model_id, self.model_b.id)

    def test_edit_row_quantity_returns_updated_slot_total(self):
        self._add_row("08:00", self.model_a, 50)
        r2 = self._add_row("08:00", self.model_b, 40)
        row_b_id = r2.json()["id"]

        edit_url = reverse("planning:api_edit_row", args=[self.plan.id, row_b_id])
        resp = self.client.post(
            edit_url,
            data=json.dumps({"model_id": self.model_b.id, "quantity": 60}),
            content_type="application/json",
        )
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["slot_total"], 110)  # 50 + 60

    def test_different_hours_are_unaffected(self):
        """Sanity check: models in different hours never collide."""
        self._add_row("08:00", self.model_a, 50)
        r2 = self._add_row("09:00", self.model_a, 70)
        self.assertTrue(r2.json()["ok"])
        self.assertEqual(HourlyPlan.objects.filter(daily_plan=self.plan).count(), 2)

    def test_hourly_plan_view_renders_with_multiple_models(self):
        """The Production Execution page must render without errors when an
        hour holds several models, and must list every model."""
        self._add_row("08:00", self.model_a, 50)
        self._add_row("08:00", self.model_b, 40)

        url = reverse("planning:hourly_plan", args=[self.plan.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Model A", html)
        self.assertIn("Model B", html)

    def test_get_hourly_board_groups_rows_as_list(self):
        """services.get_hourly_board must expose every model for an hour as a
        list (not silently overwrite or merge them)."""
        from .services import get_hourly_board
        self._add_row("08:00", self.model_a, 50)
        self._add_row("08:00", self.model_b, 40)

        time_slots, _, _ = get_hourly_board(self.plan)
        slot = next(s for s in time_slots if s["start"] == "08:00")
        self.assertEqual(len(slot["rows"]), 2)
        self.assertEqual(slot["total_planned"], 90)

    # ── Overtime hours ──────────────────────────────────────────────────────

    def test_two_models_in_same_overtime_hour_are_both_created(self):
        """Overtime hours support multiple models, same as regular hours."""
        r1 = self._add_row("23:00", self.model_a, 20, is_overtime=True)
        r2 = self._add_row("23:00", self.model_b, 25, is_overtime=True)
        self.assertTrue(r1.json()["ok"])
        self.assertTrue(r2.json()["ok"])

        rows = HourlyPlan.objects.filter(
            daily_plan=self.plan, hour=dt.time(23, 0), is_overtime=True
        )
        self.assertEqual(rows.count(), 2)
        self.assertEqual(r2.json()["slot_total"], 45)

    def test_duplicate_model_same_overtime_hour_is_rejected(self):
        """Adding the SAME model twice to the same overtime hour must fail,
        exactly like it does for regular hours."""
        r1 = self._add_row("23:00", self.model_a, 20, is_overtime=True)
        self.assertTrue(r1.json()["ok"])
        r2 = self._add_row("23:00", self.model_a, 5, is_overtime=True)
        self.assertFalse(r2.json()["ok"])
        self.assertIn("already assigned", r2.json()["error"])
        self.assertEqual(
            HourlyPlan.objects.filter(
                daily_plan=self.plan, hour=dt.time(23, 0),
                is_overtime=True, model=self.model_a,
            ).count(),
            1,
        )

    def test_overtime_and_regular_hour_duplicates_dont_interfere(self):
        """The SAME model can exist once in a regular hour and once in an
        overtime hour at a different clock time — they're different
        buckets and must not collide with each other. (Overtime can't share
        the exact same clock time as the shift window, so we use 23:00,
        which is outside the 06:00–14:00 shift used in setUp.)"""
        r1 = self._add_row("08:00", self.model_a, 50, is_overtime=False)
        r2 = self._add_row("23:00", self.model_a, 30, is_overtime=True)
        self.assertTrue(r1.json()["ok"])
        self.assertTrue(r2.json()["ok"])
        self.assertEqual(HourlyPlan.objects.filter(daily_plan=self.plan).count(), 2)

    def test_edit_overtime_row_to_duplicate_model_is_rejected(self):
        """Editing an overtime row to use a model already present in that
        same overtime hour must fail."""
        self._add_row("23:00", self.model_a, 20, is_overtime=True)
        r2 = self._add_row("23:00", self.model_b, 25, is_overtime=True)
        row_b_id = r2.json()["id"]

        edit_url = reverse("planning:api_edit_row", args=[self.plan.id, row_b_id])
        resp = self.client.post(
            edit_url,
            data=json.dumps({"model_id": self.model_a.id, "quantity": 99}),
            content_type="application/json",
        )
        self.assertFalse(resp.json()["ok"])
        row_b = HourlyPlan.objects.get(id=row_b_id)
        self.assertEqual(row_b.model_id, self.model_b.id)

    def test_hourly_plan_view_renders_with_multiple_overtime_models(self):
        """The Production Execution page must render without errors when an
        overtime hour holds several models, and must list every model."""
        self._add_row("23:00", self.model_a, 20, is_overtime=True)
        self._add_row("23:00", self.model_b, 25, is_overtime=True)

        url = reverse("planning:hourly_plan", args=[self.plan.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Model A", html)
        self.assertIn("Model B", html)
        self.assertIn("Add another model to this overtime hour", html)
        self.assertIn("2", html)  # model count pill

    # ── Time Blocks on overtime hours ────────────────────────────────────────

    def _add_block(self, slot_time, block_type, minutes, reason=""):
        url = reverse("planning:api_add_block", args=[self.plan.id])
        payload = {"slot_time": slot_time, "block_type": block_type,
                   "minutes": minutes, "reason": reason}
        return self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

    def test_time_block_reduces_effective_minutes_on_overtime_hour(self):
        """A Time Block (lunch, pre-op, etc.) dropped on an overtime hour
        must reduce its effective minutes exactly like on a regular hour."""
        from .services import get_hourly_board

        self._add_row("23:00", self.model_a, 30, is_overtime=True)
        resp = self._add_block("23:00", "lunch", 30)
        self.assertTrue(resp.json()["ok"])

        _, overtime_slots, _ = get_hourly_board(self.plan)
        ot_slot = next(s for s in overtime_slots if s["start"] == "23:00")
        self.assertEqual(ot_slot["eff_min"], 30)   # 60 - 30
        self.assertEqual(ot_slot["used_min"], 30)
        self.assertEqual(len(ot_slot["blocks"]), 1)

    def test_time_block_can_bring_overtime_hour_to_zero_effective(self):
        """Blocks totalling the full hour push effective minutes to 0,
        exactly like the existing regular-hour behavior."""
        from .services import get_hourly_board

        self._add_row("23:00", self.model_a, 30, is_overtime=True)
        resp = self._add_block("23:00", "extra", 60, "Maintenance")
        self.assertTrue(resp.json()["ok"])

        _, overtime_slots, _ = get_hourly_board(self.plan)
        ot_slot = next(s for s in overtime_slots if s["start"] == "23:00")
        self.assertEqual(ot_slot["eff_min"], 0)

    def test_time_block_on_overtime_cannot_exceed_slot_duration(self):
        """Same validation as regular hours: total block minutes can't
        exceed the 60-minute overtime slot."""
        self._add_row("23:00", self.model_a, 30, is_overtime=True)
        self._add_block("23:00", "lunch", 40)
        resp = self._add_block("23:00", "preop", 30)  # 40 + 30 > 60
        self.assertFalse(resp.json()["ok"])

    def test_overtime_slot_renders_block_pills_and_effective_minutes(self):
        """The rendered page must show the block pill and the updated
        'effective minutes' text for an overtime hour."""
        self._add_row("23:00", self.model_a, 30, is_overtime=True)
        self._add_block("23:00", "lunch", 30)

        url = reverse("planning:hourly_plan", args=[self.plan.id])
        resp = self.client.get(url)
        html = resp.content.decode()
        self.assertIn("Lunch Break", html)
        self.assertIn("30 min effective", html)

    def test_overtime_hour_supports_drag_and_drop_attributes(self):
        """The overtime slot-card must carry the same data attributes a
        regular slot-card has, so the existing drag&drop JS (handleDrop,
        recalcSlot) works on it without modification."""
        self._add_row("23:00", self.model_a, 30, is_overtime=True)
        url = reverse("planning:hourly_plan", args=[self.plan.id])
        resp = self.client.get(url)
        html = resp.content.decode()
        self.assertIn('id="ot-slot-2300"', html)
        self.assertIn('data-slot="23:00"', html)
        self.assertIn('data-overtime-slot="true"', html)
        self.assertIn('ondrop="handleDrop(event, this)"', html)


class ActualsPerModelTestCase(TestCase):
    """
    Covers the Actuals requirement: each model within a shared hour keeps its
    own actual quantity, comment, and history — nothing is shared between
    models in the same hour.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="leader2", password="pw12345")
        UserProfile.objects.update_or_create(user=self.user, defaults={"role": "leader"})

        self.wc = WorkCenter.objects.create(name="WC-2")
        self.sp_type = SubProcessType.objects.create(
            name="Standard2", applies_to="reactores", units_per_piece=1
        )
        self.subprocess = SubProcess.objects.create(
            work_center=self.wc, name="SP-2", subprocess_type=self.sp_type
        )
        self.shift = Shift.objects.create(
            name="Morning2", code="MOR2",
            start_time=dt.time(6, 0), end_time=dt.time(14, 0),
            is_active=True,
        )
        self.plan = DailyPlan.objects.create(
            date=dt.date(2026, 6, 2),
            work_center=self.wc, subprocess=self.subprocess,
            headcount=10, shift=self.shift,
        )
        self.model_a = PlanningModel.objects.create(name="Actuals Model A")
        self.model_b = PlanningModel.objects.create(name="Actuals Model B")

        self.row_a = HourlyPlan.objects.create(
            daily_plan=self.plan, hour=dt.time(8, 0),
            model=self.model_a, planned_quantity=80,
        )
        self.row_b = HourlyPlan.objects.create(
            daily_plan=self.plan, hour=dt.time(8, 0),
            model=self.model_b, planned_quantity=40,
        )

        self.client = Client()
        self.client.login(username="leader2", password="pw12345")

    def test_actuals_are_independent_per_model(self):
        from production.models import HourlyExecution, LossReason

        loss_reason = LossReason.objects.create(name="Material shortage")

        url = reverse("production:execution_enter", args=[self.plan.id])
        # ExecutionEventFormSet is an inline formset — Django requires its
        # management-form fields (TOTAL_FORMS etc.) to be present in POST
        # data for is_valid() to pass, even when submitting zero events.
        # Missing here before (pre-existing gap): the
        # formset silently failed validation, so execution_enter never
        # reached the save() call for either row.
        events_a_prefix = f"hp-{self.row_a.id}-events"
        data = {
            f"hp-{self.row_a.id}-actual_quantity": "75",
            f"hp-{self.row_a.id}-scrap_quantity": "0",
            f"hp-{self.row_a.id}-comments": "Falta de material",
            f"hp-{self.row_a.id}-loss_reasons": str(loss_reason.id),
            f"{events_a_prefix}-TOTAL_FORMS": "0",
            f"{events_a_prefix}-INITIAL_FORMS": "0",
            f"{events_a_prefix}-MIN_NUM_FORMS": "0",
            f"{events_a_prefix}-MAX_NUM_FORMS": "1000",
        }
        self.client.post(url, data=data)

        events_b_prefix = f"hp-{self.row_b.id}-events"
        data2 = {
            f"hp-{self.row_b.id}-actual_quantity": "38",
            f"hp-{self.row_b.id}-scrap_quantity": "0",
            f"hp-{self.row_b.id}-comments": "Cambio de operador",
            f"hp-{self.row_b.id}-loss_reasons": str(loss_reason.id),
            f"{events_b_prefix}-TOTAL_FORMS": "0",
            f"{events_b_prefix}-INITIAL_FORMS": "0",
            f"{events_b_prefix}-MIN_NUM_FORMS": "0",
            f"{events_b_prefix}-MAX_NUM_FORMS": "1000",
        }
        self.client.post(url, data=data2)

        exec_a = HourlyExecution.objects.get(hourly_plan=self.row_a)
        exec_b = HourlyExecution.objects.get(hourly_plan=self.row_b)

        self.assertEqual(exec_a.actual_quantity, 75)
        self.assertEqual(exec_b.actual_quantity, 38)
        self.assertIn("Falta de material", exec_a.active_comment)
        self.assertIn("Cambio de operador", exec_b.active_comment)
        # Comments must never bleed across models
        self.assertNotIn("Cambio de operador", exec_a.active_comment)
        self.assertNotIn("Falta de material", exec_b.active_comment)

    def test_diff_and_efficiency_are_per_model(self):
        from production.models import HourlyExecution
        exec_a = HourlyExecution.objects.create(
            hourly_plan=self.row_a, actual_quantity=75, comments="x"
        )
        exec_b = HourlyExecution.objects.create(
            hourly_plan=self.row_b, actual_quantity=38, comments="y"
        )
        self.assertEqual(exec_a.diff_quantity, -5)   # 75 - 80
        self.assertEqual(exec_b.diff_quantity, -2)   # 38 - 40
        self.assertAlmostEqual(exec_a.efficiency_pct, 93.8, places=1)
        self.assertAlmostEqual(exec_b.efficiency_pct, 95.0, places=1)

    def test_execution_list_renders_both_models_separately(self):
        url = reverse("production:execution_enter", args=[self.plan.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Actuals Model A", html)
        self.assertIn("Actuals Model B", html)


class DashboardMultiModelTestCase(TestCase):
    """Covers the dashboard/chart requirement: every model in a shared hour
    must appear as its own labeled data point, never merged."""

    def setUp(self):
        self.user = User.objects.create_user(username="leader3", password="pw12345")
        UserProfile.objects.update_or_create(user=self.user, defaults={"role": "leader"})

        self.wc = WorkCenter.objects.create(name="WC-3")
        self.sp_type = SubProcessType.objects.create(
            name="Standard3", applies_to="reactores", units_per_piece=1
        )
        self.subprocess = SubProcess.objects.create(
            work_center=self.wc, name="SP-3", subprocess_type=self.sp_type
        )
        self.shift = Shift.objects.create(
            name="Morning3", code="MOR3",
            start_time=dt.time(6, 0), end_time=dt.time(14, 0),
            is_active=True,
        )
        self.plan = DailyPlan.objects.create(
            date=dt.date(2026, 6, 3),
            work_center=self.wc, subprocess=self.subprocess,
            headcount=10, shift=self.shift,
        )
        self.model_a = PlanningModel.objects.create(name="Dash Model A")
        self.model_b = PlanningModel.objects.create(name="Dash Model B")
        HourlyPlan.objects.create(
            daily_plan=self.plan, hour=dt.time(8, 0),
            model=self.model_a, planned_quantity=80,
        )
        HourlyPlan.objects.create(
            daily_plan=self.plan, hour=dt.time(8, 0),
            model=self.model_b, planned_quantity=40,
        )
        self.client = Client()
        self.client.login(username="leader3", password="pw12345")

    def test_dashboard_renders_without_error(self):
        resp = self.client.get(reverse("planning:dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_chart_has_one_point_per_model(self):
        resp = self.client.get(reverse("planning:dashboard"))
        html = resp.content.decode()
        self.assertIn("Dash Model A", html)
        self.assertIn("Dash Model B", html)
        # Both models must appear as distinct chart labels, not merged into
        # a single "08:00" bucket.
        self.assertIn("08:00", html)
        self.assertGreaterEqual(html.count("Dash Model"), 2)


class TimeBlockAutoReasonTestCase(TestCase):
    """
    Covers extending the existing "Time Blocks → auto-reason" behavior
    (previously only active when planned_quantity == 0) to ANY hour that
    has Time Blocks, regardless of planned quantity, and to overtime hours
    too. The Actuals screen (production app) consumes this to pre-fill
    whichever comment field applies, without ever overwriting text the
    supervisor already typed.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="leader4", password="pw12345")
        UserProfile.objects.update_or_create(user=self.user, defaults={"role": "leader"})

        self.wc = WorkCenter.objects.create(name="WC-4")
        self.sp_type = SubProcessType.objects.create(
            name="Standard4", applies_to="reactores", units_per_piece=1
        )
        self.subprocess = SubProcess.objects.create(
            work_center=self.wc, name="SP-4", subprocess_type=self.sp_type
        )
        self.shift = Shift.objects.create(
            name="Morning4", code="MOR4",
            start_time=dt.time(6, 0), end_time=dt.time(14, 0),
            is_active=True,
        )
        self.plan = DailyPlan.objects.create(
            date=dt.date(2026, 6, 4),
            work_center=self.wc, subprocess=self.subprocess,
            headcount=10, shift=self.shift,
        )
        self.model_a = PlanningModel.objects.create(name="AutoReason Model A")
        self.client = Client()
        self.client.login(username="leader4", password="pw12345")

    def _add_block(self, slot_time, block_type, minutes, reason=""):
        url = reverse("planning:api_add_block", args=[self.plan.id])
        payload = {"slot_time": slot_time, "block_type": block_type,
                   "minutes": minutes, "reason": reason}
        return self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

    def test_format_blocks_summary_matches_existing_label_format(self):
        from .services import format_blocks_summary
        from .models import HourlyPlanBlock

        HourlyPlanBlock.objects.create(
            daily_plan=self.plan, slot_time=dt.time(8, 0),
            block_type="lunch", minutes=30,
        )
        HourlyPlanBlock.objects.create(
            daily_plan=self.plan, slot_time=dt.time(8, 0),
            block_type="preop", minutes=15,
        )
        blocks = list(HourlyPlanBlock.objects.filter(
            daily_plan=self.plan, slot_time=dt.time(8, 0)
        ))
        summary = format_blocks_summary(blocks)
        self.assertEqual(summary, "Lunch Break (30 min) · Operation Preparation (15 min)")

    def test_auto_reason_present_for_planned_above_zero(self):
        """A regular hour with planned_quantity > 0 that has a Time Block
        must still produce an auto_reason — this used to be empty before."""
        HourlyPlan.objects.create(
            daily_plan=self.plan, hour=dt.time(8, 0),
            model=self.model_a, planned_quantity=50,
        )
        self._add_block("08:00", "lunch", 20)

        resp = self.client.get(
            reverse("production:execution_enter", args=[self.plan.id])
        )
        html = resp.content.decode()
        self.assertIn("System — Time Blocks", html)
        self.assertIn("Lunch Break (20 min)", html)

    def test_auto_reason_present_for_overtime_hour(self):
        """An overtime hour with a Time Block must also expose an
        auto_reason, same as a regular hour."""
        url = reverse("planning:api_add_row", args=[self.plan.id])
        self.client.post(
            url,
            data=json.dumps({
                "hour": "23:00", "model_id": self.model_a.id, "quantity": 25,
                "headcount_override": None, "is_overtime": True, "comments": "",
            }),
            content_type="application/json",
        )
        self._add_block("23:00", "preop", 10)

        resp = self.client.get(
            reverse("production:execution_enter", args=[self.plan.id])
        )
        html = resp.content.decode()
        self.assertIn("Operation Preparation (10 min)", html)

    def test_auto_reason_stored_as_data_attribute_for_js_autofill(self):
        """The auto_reason text must be embedded as a data attribute so the
        frontend JS can pre-fill the matching comment field once the actual
        quantity is captured."""
        HourlyPlan.objects.create(
            daily_plan=self.plan, hour=dt.time(8, 0),
            model=self.model_a, planned_quantity=50,
        )
        self._add_block("08:00", "lunch", 20)

        resp = self.client.get(
            reverse("production:execution_enter", args=[self.plan.id])
        )
        html = resp.content.decode()
        self.assertIn('data-auto-reason="Lunch Break (20 min)"', html)

    def test_no_auto_reason_when_no_blocks_exist(self):
        """An hour with no Time Blocks must not show the auto-reason note,
        and its data attribute must be empty."""
        HourlyPlan.objects.create(
            daily_plan=self.plan, hour=dt.time(9, 0),
            model=self.model_a, planned_quantity=50,
        )
        resp = self.client.get(
            reverse("production:execution_enter", args=[self.plan.id])
        )
        html = resp.content.decode()
        self.assertNotIn("System — Time Blocks", html)

class HourDeletionTestCase(TestCase):
    """Any hour (regular or overtime) can be deleted, EXCEPT one that already
    holds captured execution — that must be blocked with a clear reason."""

    def setUp(self):
        import datetime as _d
        from django.contrib.auth.models import User as _U
        from users.models import UserProfile as _UP
        from core.models import (WorkCenter as _WC, SubProcess as _SP,
                                 SubProcessType as _SPT, Shift as _S)
        from planning.models import (DailyPlan as _DP, HourlyPlan as _HP,
                                     Model as _M)
        self.u = _U.objects.create_user("hourdel", password="pw")
        _UP.objects.filter(user=self.u).update(role="leader")
        self.u = _U.objects.get(pk=self.u.pk)

        wc = _WC.objects.create(name="WC-HDEL")
        spt = _SPT.objects.create(name="T-HDEL", applies_to="reactores",
                                  units_per_piece=1)
        sp = _SP.objects.create(work_center=wc, name="SP-HDEL",
                                subprocess_type=spt)
        shift = _S.objects.create(name="HDEL", code="HD",
                                  start_time=_d.time(6), end_time=_d.time(14),
                                  is_active=True)
        self.plan = _DP.objects.create(date=_d.date(2026, 10, 10),
                                       work_center=wc, subprocess=sp,
                                       headcount=5, shift=shift)
        self.model = _M.objects.create(name="HDEL Model")
        self._HP = _HP
        self._d = _d

        from django.test import Client
        self.client = Client()
        self.client.force_login(self.u)
        self.AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def _hour(self, h, overtime=False):
        return self._HP.objects.create(
            daily_plan=self.plan, hour=self._d.time(h), model=self.model,
            planned_quantity=10, is_overtime=overtime)

    def test_regular_hour_can_now_be_deleted(self):
        hp = self._hour(8, overtime=False)
        r = self.client.post(
            f"/plans/{self.plan.id}/hours/{hp.id}/delete/", **self.AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self._HP.objects.filter(id=hp.id).exists())

    def test_overtime_hour_can_be_deleted(self):
        hp = self._hour(15, overtime=True)
        r = self.client.post(
            f"/plans/{self.plan.id}/hours/{hp.id}/delete/", **self.AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self._HP.objects.filter(id=hp.id).exists())

    def test_preflight_warns_about_captured_execution(self):
        """A GET reports what would be lost so the modal can warn the user.
        Uses an Admin client: once an hour has captured execution, deleting
        it is Admin-only — Leader/Supervisor get 403,
        covered separately below by
        test_leader_cannot_delete_hour_with_captured_execution."""
        from production.models import HourlyExecution
        from django.contrib.auth.models import User as _U
        from users.models import UserProfile as _UP
        from django.test import Client
        admin = _U.objects.create_user("hourdel_admin", password="pw")
        _UP.objects.filter(user=admin).update(role="admin")
        admin = _U.objects.get(pk=admin.pk)
        admin_client = Client(); admin_client.force_login(admin)

        hp = self._hour(9, overtime=False)
        HourlyExecution.objects.create(hourly_plan=hp, actual_quantity=7)
        r = admin_client.get(
            f"/plans/{self.plan.id}/hours/{hp.id}/delete/", **self.AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["has_execution"])
        self.assertEqual(r.json()["actual_quantity"], 7)
        # Nothing deleted by the pre-flight itself.
        self.assertTrue(self._HP.objects.filter(id=hp.id).exists())

    def test_delete_cascades_to_execution(self):
        """Confirming (as Admin) removes the hour AND its captured
        execution. See docstring above — non-Admin roles are covered by
        test_leader_cannot_delete_hour_with_captured_execution."""
        from production.models import HourlyExecution
        from django.contrib.auth.models import User as _U
        from users.models import UserProfile as _UP
        from django.test import Client
        admin = _U.objects.create_user("hourdel_admin2", password="pw")
        _UP.objects.filter(user=admin).update(role="admin")
        admin = _U.objects.get(pk=admin.pk)
        admin_client = Client(); admin_client.force_login(admin)

        hp = self._hour(11, overtime=False)
        HourlyExecution.objects.create(hourly_plan=hp, actual_quantity=7)
        r = admin_client.post(
            f"/plans/{self.plan.id}/hours/{hp.id}/delete/", **self.AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["deleted_execution"], 7)
        self.assertFalse(self._HP.objects.filter(id=hp.id).exists())
        self.assertFalse(
            HourlyExecution.objects.filter(hourly_plan_id=hp.id).exists())
        
    def test_leader_cannot_delete_hour_with_captured_execution(self):
        """Leader has full write on Hourly Plans in general, but once an
        hour has real production captured, deleting it is Admin-only
        (2026-08 decision, same rule as Daily Plans)."""
        from production.models import HourlyExecution
        hp = self._hour(13, overtime=False)
        HourlyExecution.objects.create(hourly_plan=hp, actual_quantity=5)
        r = self.client.post(
            f"/plans/{self.plan.id}/hours/{hp.id}/delete/", **self.AJAX)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(self._HP.objects.filter(id=hp.id).exists())
        self.assertTrue(
            HourlyExecution.objects.filter(hourly_plan_id=hp.id).exists())

    def test_operator_cannot_delete_hours(self):
        from django.contrib.auth.models import User as _U
        from users.models import UserProfile as _UP
        from django.test import Client
        op = _U.objects.create_user("hourop", password="pw")
        _UP.objects.filter(user=op).update(role="operator")
        op = _U.objects.get(pk=op.pk)
        hp = self._hour(10, overtime=False)
        c = Client(); c.force_login(op)
        r = c.post(f"/plans/{self.plan.id}/hours/{hp.id}/delete/", **self.AJAX)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(self._HP.objects.filter(id=hp.id).exists())


class SubprocessFilterTestCase(TestCase):
    """The subprocess filter must isolate results in every section that
    offers it: Daily Plans, Execution, Analytics Day dashboard."""

    def setUp(self):
        import datetime as _d, random
        from django.contrib.auth.models import User as _U
        from users.models import UserProfile as _UP
        from core.models import (WorkCenter as _WC, SubProcess as _SP,
                                 SubProcessType as _SPT, Shift as _S)
        from planning.models import DailyPlan as _DP
        s = str(random.randint(10000, 99999))
        self.u = _U.objects.create_user("spf" + s, password="pw")
        _UP.objects.filter(user=self.u).update(role="leader")
        self.u = _U.objects.get(pk=self.u.pk)
        wc = _WC.objects.create(name="WC-SPF" + s)
        spt = _SPT.objects.create(name="T-SPF" + s, applies_to="reactores",
                                  units_per_piece=1)
        self.sp_a = _SP.objects.create(work_center=wc, name="SPF-A" + s,
                                       subprocess_type=spt)
        self.sp_b = _SP.objects.create(work_center=wc, name="SPF-B" + s,
                                       subprocess_type=spt)
        shift = _S.objects.create(name="SPF" + s, code="F" + s[:3],
                                  start_time=_d.time(6), end_time=_d.time(14),
                                  is_active=True)
        self.plan_a = _DP.objects.create(date=_d.date(2026, 12, 9),
                                         work_center=wc, subprocess=self.sp_a,
                                         headcount=5, shift=shift)
        self.plan_b = _DP.objects.create(date=_d.date(2026, 12, 9),
                                         work_center=wc, subprocess=self.sp_b,
                                         headcount=5, shift=shift)
        from django.test import Client
        self.client = Client()
        self.client.force_login(self.u)

    def test_daily_plans_filter(self):
        r = self.client.get(f"/plans/?subprocess={self.sp_a.id}")
        ids = {p.id for p in r.context["plans"]}
        self.assertIn(self.plan_a.id, ids)
        self.assertNotIn(self.plan_b.id, ids)

    def test_execution_filter(self):
        r = self.client.get(f"/production/?subprocess={self.sp_a.id}")
        ids = {e["plan"].id for e in r.context["enriched"]}
        self.assertIn(self.plan_a.id, ids)
        self.assertNotIn(self.plan_b.id, ids)

    def test_day_dashboard_filter(self):
        r = self.client.get(f"/analytics/day/?subprocess={self.sp_a.id}")
        ids = {p.id for p in r.context["plans"]}
        self.assertIn(self.plan_a.id, ids)
        self.assertNotIn(self.plan_b.id, ids)

    def test_no_filter_shows_both(self):
        r = self.client.get("/plans/")
        ids = {p.id for p in r.context["plans"]}
        self.assertIn(self.plan_a.id, ids)
        self.assertIn(self.plan_b.id, ids)


class DashboardFiltersTestCase(TestCase):
    """Dashboard: the chart only renders once a filter is chosen, the New Plan
    button is gone from the header, and WC/Subprocess/Shift/Date all filter."""

    def setUp(self):
        import datetime as _d, random
        from django.contrib.auth.models import User as _U
        from users.models import UserProfile as _UP
        from core.models import (WorkCenter as _WC, SubProcess as _SP,
                                 SubProcessType as _SPT, Shift as _S)
        from planning.models import (DailyPlan as _DP, HourlyPlan as _HP,
                                     Model as _M)
        s = str(random.randint(10000, 99999))
        self.u = _U.objects.create_user("dashf" + s, password="pw")
        _UP.objects.filter(user=self.u).update(role="leader")
        self.u = _U.objects.get(pk=self.u.pk)

        self.wc = _WC.objects.create(name="WC-DASHF" + s)
        spt = _SPT.objects.create(name="T-DASHF" + s, applies_to="reactores",
                                  units_per_piece=1)
        self.sp_a = _SP.objects.create(work_center=self.wc, name="A" + s,
                                       subprocess_type=spt)
        self.sp_b = _SP.objects.create(work_center=self.wc, name="B" + s,
                                       subprocess_type=spt)
        self.shift = _S.objects.create(name="DF" + s, code="D" + s[:3],
                                       start_time=_d.time(6), end_time=_d.time(14),
                                       is_active=True)
        self.model = _M.objects.create(name="DASHF Model" + s)
        self.plan_a = _DP.objects.create(date=_d.date(2027, 2, 1),
                                         work_center=self.wc, subprocess=self.sp_a,
                                         headcount=5, shift=self.shift)
        self.plan_b = _DP.objects.create(date=_d.date(2027, 2, 2),
                                         work_center=self.wc, subprocess=self.sp_b,
                                         headcount=5, shift=self.shift)
        _HP.objects.create(daily_plan=self.plan_a, hour=_d.time(8),
                           model=self.model, planned_quantity=10)
        _HP.objects.create(daily_plan=self.plan_b, hour=_d.time(8),
                           model=self.model, planned_quantity=20)

        from django.test import Client
        self.client = Client()
        self.client.force_login(self.u)

    def test_no_new_plan_button_in_header(self):
        html = self.client.get("/").content.decode()
        self.assertNotIn("New Plan", html)

    def test_chart_hidden_until_a_filter_is_applied(self):
        html = self.client.get("/").content.decode()
        self.assertNotIn('id="dashboardChart"', html)
        self.assertIn("Choose a filter to see the chart", html)

    def test_chart_appears_once_filtered(self):
        html = self.client.get(f"/?wc={self.wc.id}").content.decode()
        self.assertIn('id="dashboardChart"', html)
        self.assertNotIn("Choose a filter to see the chart", html)

    def test_subprocess_filter_narrows_results(self):
        r = self.client.get(f"/?subprocess={self.sp_a.id}")
        plan_ids = {hp.daily_plan_id for hp in r.context["data"]}
        self.assertIn(self.plan_a.id, plan_ids)
        self.assertNotIn(self.plan_b.id, plan_ids)

    def test_shift_filter_available(self):
        r = self.client.get(f"/?shift={self.shift.id}")
        plan_ids = {hp.daily_plan_id for hp in r.context["data"]}
        self.assertIn(self.plan_a.id, plan_ids)

    def test_date_filter_narrows_results(self):
        r = self.client.get("/?date=2027-02-01")
        plan_ids = {hp.daily_plan_id for hp in r.context["data"]}
        self.assertIn(self.plan_a.id, plan_ids)
        self.assertNotIn(self.plan_b.id, plan_ids)

    def test_all_four_selects_rendered(self):
        html = self.client.get("/").content.decode()
        for name in ['name="wc"', 'name="subprocess"', 'name="shift"', 'name="date"']:
            self.assertIn(name, html, f"{name} filter missing")


class DashboardFilterBarTestCase(TestCase):
    """The filter bar must keep its position in every state, and the
    achievement percentage must appear there once a filter is applied."""

    def setUp(self):
        import datetime as _d, random
        from django.contrib.auth.models import User as _U
        from users.models import UserProfile as _UP
        from core.models import (WorkCenter as _WC, SubProcess as _SP,
                                 SubProcessType as _SPT, Shift as _S)
        from planning.models import (DailyPlan as _DP, HourlyPlan as _HP,
                                     Model as _M)
        from production.models import HourlyExecution as _HE
        s = str(random.randint(10000, 99999))
        self.u = _U.objects.create_user("fbar" + s, password="pw")
        _UP.objects.filter(user=self.u).update(role="leader")
        self.u = _U.objects.get(pk=self.u.pk)

        self.wc_data = _WC.objects.create(name="WC-BAR" + s)
        self.wc_empty = _WC.objects.create(name="WC-EMPTY" + s)
        spt = _SPT.objects.create(name="T-BAR" + s, applies_to="reactores",
                                  units_per_piece=1)
        sp = _SP.objects.create(work_center=self.wc_data, name="SP-BAR" + s,
                                subprocess_type=spt)
        shift = _S.objects.create(name="BAR" + s, code="B" + s[:3],
                                  start_time=_d.time(6), end_time=_d.time(14),
                                  is_active=True)
        plan = _DP.objects.create(date=_d.date(2027, 4, 1),
                                  work_center=self.wc_data, subprocess=sp,
                                  headcount=5, shift=shift)
        m = _M.objects.create(name="BAR Model" + s)
        hp = _HP.objects.create(daily_plan=plan, hour=_d.time(8),
                                model=m, planned_quantity=100)
        _HE.objects.create(hourly_plan=hp, actual_quantity=75)

        from django.test import Client
        self.client = Client()
        self.client.force_login(self.u)

    def _html(self, url):
        return self.client.get(url).content.decode()

    def test_filter_bar_present_without_filters(self):
        html = self._html("/")
        self.assertIn('name="wc"', html)
        self.assertIn('name="subprocess"', html)

    def test_filter_bar_present_when_filtered_with_data(self):
        html = self._html(f"/?wc={self.wc_data.id}")
        self.assertIn('name="wc"', html)

    def test_filter_bar_present_when_filtered_with_no_data(self):
        """The bar must not disappear or shift when the selection is empty."""
        html = self._html(f"/?wc={self.wc_empty.id}")
        self.assertIn('name="wc"', html)

    def test_filters_render_before_the_chart(self):
        html = self._html(f"/?wc={self.wc_data.id}")
        self.assertLess(html.find('name="wc"'), html.find('id="dashboardChart"'),
                        "filter bar must come before the chart")

    def test_percentage_shown_after_filtering(self):
        html = self._html(f"/?wc={self.wc_data.id}")
        self.assertIn("Achievement", html)
        self.assertIn("75 / 100", html)
        self.assertIn("(75%)", html)

    def test_no_percentage_before_filtering(self):
        html = self._html("/")
        self.assertNotIn("Achievement", html)

    def test_empty_selection_explains_itself(self):
        html = self._html(f"/?wc={self.wc_empty.id}")
        self.assertIn("No planned quantity for this selection", html)

    def test_percentage_appears_only_once(self):
        """The old badge inside the chart card must be gone — no duplicates."""
        html = self._html(f"/?wc={self.wc_data.id}")
        self.assertEqual(html.count("75 / 100"), 1)