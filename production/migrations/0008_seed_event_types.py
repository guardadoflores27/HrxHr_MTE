# Generated manually — seeds the default Operational Events catalog.
from django.db import migrations

DEFAULT_EVENT_TYPES = [
    # (name, icon, color, requires_comment, order)
    ("Lunch",               "fa-utensils",           "amber",   False, 10),
    ("Chair Time",          "fa-chair",              "slate",   False, 20),
    ("Meeting",             "fa-people-group",       "blue",    False, 30),
    ("Training",            "fa-graduation-cap",     "violet",  False, 40),
    ("Maintenance",         "fa-screwdriver-wrench", "red",     False, 50),
    ("Cleaning",            "fa-broom",              "teal",    False, 60),
    ("Material Waiting",    "fa-box-open",           "orange",  False, 70),
    ("Quality Inspection",  "fa-magnifying-glass",   "indigo",  False, 80),
    ("Safety Meeting",      "fa-shield-halved",      "rose",    False, 90),
    ("Machine Setup",       "fa-gears",              "cyan",    False, 100),
    ("Machine Adjustment",  "fa-wrench",             "cyan",    False, 110),
    ("Inventory",           "fa-clipboard-list",     "lime",    False, 120),
    ("Other",               "fa-ellipsis",           "gray",    True,  999),
]


def seed_event_types(apps, schema_editor):
    EventType = apps.get_model("production", "EventType")
    for name, icon, color, requires_comment, order in DEFAULT_EVENT_TYPES:
        EventType.objects.update_or_create(
            name=name,
            defaults={
                "icon": icon,
                "color": color,
                "requires_comment": requires_comment,
                "order": order,
                "is_active": True,
            },
        )


def unseed_event_types(apps, schema_editor):
    EventType = apps.get_model("production", "EventType")
    EventType.objects.filter(
        name__in=[row[0] for row in DEFAULT_EVENT_TYPES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("production", "0007_eventtype_executionevent"),
    ]

    operations = [
        migrations.RunPython(seed_event_types, unseed_event_types),
    ]
