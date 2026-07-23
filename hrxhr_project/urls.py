"""
URL configuration for hrxhr_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# hrxhr_project/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("",          include("planning.urls",    namespace="planning")),
    path("production/", include("production.urls", namespace="production")),
    path("core/",     include("core.urls",         namespace="core")),
    path("users/",    include("users.urls",         namespace="users")),
    path("analytics/", include("analytics.urls",    namespace="analytics")),
]


"""
URL configuration for hrxhr_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# hrxhr_project/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("",          include("planning.urls",    namespace="planning")),
    path("production/", include("production.urls", namespace="production")),
    path("core/",     include("core.urls",         namespace="core")),
    path("users/",    include("users.urls",         namespace="users")),
    path("analytics/", include("analytics.urls",    namespace="analytics")),
]