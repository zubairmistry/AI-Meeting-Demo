from django.urls import path
from . import views

urlpatterns = [

    path(
        "",
        views.home,
        name="meeting"
    ),

    path(
        "settings/",
        views.settings,
        name="settings"
    ),

    path(
        "dashboard/",
        views.dashboard,
        name="dashboard"
    ),

    path(
        "meeting/<int:meeting_id>/",
        views.meeting_detail,
        name="meeting_detail",
    ),

    path(
        "register/",
        views.register,
        name="register"
    ),

    path(
        "login/",
     views.login_view,
     name="login"
    ),

    path(
        "logout/",
        views.logout_view,
        name="logout"
    ),
]