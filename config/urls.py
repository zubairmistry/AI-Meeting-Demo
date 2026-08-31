from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("meeting.urls")),
]

if settings.DEBUG or getattr(settings, "SERVE_MEDIA", True):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
