from django.urls import path

from apps.engagement.api.views import AdminHomeEngagementView, HomeEventBatchView

urlpatterns = [
    path("home-events/", HomeEventBatchView.as_view(), name="engagement-home-events"),
    path("admin/home/", AdminHomeEngagementView.as_view(), name="engagement-admin-home"),
]
