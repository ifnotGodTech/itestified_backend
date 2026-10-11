from django.utils.cache import patch_cache_control
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny

from apps.bible import selectors

from .serializers import BiblePackSerializer

# Phones re-check the manifest on each Bible-tab open; five minutes of
# caching keeps that cheap while a newly published pack still shows up
# the same day.
PACK_LIST_MAX_AGE_SECONDS = 300


class BiblePackPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class BiblePackListView(generics.ListAPIView):
    """Public, read-only list of downloadable Bible packs (Phase 34). Open
    to guests: reading the Bible is free for everyone."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = BiblePackSerializer
    pagination_class = BiblePackPagination

    def get_queryset(self):
        return selectors.list_available_packs()

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code == 200:
            patch_cache_control(response, public=True, max_age=PACK_LIST_MAX_AGE_SECONDS)
        return response
