# production/urls.py
from django.urls import path
from . import views

app_name = "production"

urlpatterns = [
    path("",                          views.execution_list,   name="execution_list"),
    path("<int:plan_id>/",            views.execution_enter,  name="execution_enter"),
]