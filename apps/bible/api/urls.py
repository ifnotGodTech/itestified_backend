from django.urls import path

from .views import BiblePackListView

urlpatterns = [
    path("packs/", BiblePackListView.as_view(), name="bible-pack-list"),
]
