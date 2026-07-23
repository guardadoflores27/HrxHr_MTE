# users/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = "users"

urlpatterns = [
    path("login/",  auth_views.LoginView.as_view(
        template_name="users/login.html",
        redirect_authenticated_user=True,
    ), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),

    # Users Administration
    path("admin/users/",              views.user_list,      name="user_list"),
    path("admin/users/create/",       views.user_create,    name="user_create"),
    path("admin/users/edit/",         views.user_edit_list, name="user_edit_list"),
    path("admin/users/<int:pk>/edit/",   views.user_edit,   name="user_edit"),
    path("admin/users/<int:pk>/delete/", views.user_delete, name="user_delete"),
]
