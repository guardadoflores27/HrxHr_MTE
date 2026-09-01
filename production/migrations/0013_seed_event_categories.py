from django.db import migrations

# The 5 categories that planning.HourlyPlanBlock.BLOCK_TYPES and
# production.block_bridge expect to exist. All five are inherently PLANNED
# downtime — they only ever exist because a Leader/Supervisor pre-scheduled
# them as a Time Block in the Hourly Plan Board, unlike a spontaneous,
# manually-logged event (e.g. a machine breakdown) which has no category.
#
# PRE-EXISTING GAP, not caused by the Fase 1 work: migration 0010 created the
# EventCategory model and the EventType.category FK, but never seeded any
# EventCategory rows nor linked them to the EventTypes seeded back in 0008.
# On a fresh database (a real clone, or the test database — never a database
# where someone already patched this by hand in /admin/) this leaves
# EventType.category = None for everything, which is what made
# analytics.tests fail once the full suite was finally run end-to-end.
CATEGORIES = [
    # (code, name, order)
    ("lunch",   "Lunch",                 10),
    ("preop",   "Operation Preparation", 20),
    ("workfin", "Work Finalization",     30),
    ("chair",   "Chair Time",            40),
    ("extra",   "Extra Reason",          50),
]

# Matches production.block_bridge.BLOCK_CODE_TO_EVENT_TYPE_NAME exactly — the
# representative EventType each category rolls up to. "Lunch" and
# "Chair Time" already exist (seeded in 0008) and just get linked here.
# "Operation Preparation", "Work Finalization" and "Extra Reason" were never
# seeded at all, even though block_bridge.py has always expected them to
# exist by that exact name as its fallback match — this migration adds them.
EVENT_TYPE_BY_CODE = {
    "lunch":   {"name": "Lunch",                 "icon": "fa-utensils",       "color": "amber",   "order": 10},
    "chair":   {"name": "Chair Time",             "icon": "fa-chair",          "color": "slate",   "order": 20},
    "preop":   {"name": "Operation Preparation",  "icon": "fa-play",           "color": "sky",     "order": 15},
    "workfin": {"name": "Work Finalization",      "icon": "fa-flag-checkered", "color": "emerald", "order": 25},
    "extra":   {"name": "Extra Reason",           "icon": "fa-plus",          "color": "gray",    "order": 105},
}


def seed_categories(apps, schema_editor):
    EventCategory = apps.get_model("production", "EventCategory")
    EventType = apps.get_model("production", "EventType")

    for code, name, order in CATEGORIES:
        category, _ = EventCategory.objects.update_or_create(
            code=code,
            defaults={"name": name, "is_planned": True, "is_active": True, "order": order},
        )

        et_info = EVENT_TYPE_BY_CODE[code]
        EventType.objects.update_or_create(
            name=et_info["name"],
            defaults={
                "icon": et_info["icon"],
                "color": et_info["color"],
                "requires_comment": False,
                "order": et_info["order"],
                "is_active": True,
                "category": category,
            },
        )


def unseed_categories(apps, schema_editor):
    EventType = apps.get_model("production", "EventType")
    EventCategory = apps.get_model("production", "EventCategory")
    # Un-link the FK first (Lunch/Chair Time predate this migration and
    # should survive being un-linked, not be deleted).
    EventType.objects.filter(
        name__in=[v["name"] for v in EVENT_TYPE_BY_CODE.values()]
    ).update(category=None)
    EventCategory.objects.filter(code__in=[c for c, _, _ in CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("production", "0012_hourlyexecution_actual_headcount_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed_categories),
    ]
