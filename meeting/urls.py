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
        "settings/api/discover-models/",
        views.discover_models_api,
        name="discover_models_api",
    ),

    path(
        "settings/api/validate-model/",
        views.validate_model_api,
        name="validate_model_api",
    ),

    path(
        "dashboard/",
        views.dashboard,
        name="dashboard"
    ),

    path(
        "meeting/analyze/",
        views.analyze_meeting_api,
        name="analyze_meeting_api",
    ),
    path(
        "meeting/status/<int:meeting_id>/",
        views.meeting_status_api,
        name="meeting_status_api",
    ),
    path(
        "meeting/retry/<int:meeting_id>/",
        views.retry_meeting_api,
        name="retry_meeting_api",
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