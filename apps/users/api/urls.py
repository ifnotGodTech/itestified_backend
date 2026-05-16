from django.urls import path

from .views import CurrentProfileView

urlpatterns = [
    path("me/", CurrentProfileView.as_view(), name="profile-me"),
]
