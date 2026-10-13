from django.utils.cache import patch_cache_control
from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.bible import selectors
from apps.bible.exceptions import BiblePackChangeRefused
from apps.bible.services.commands import make_bible_pack_default, set_bible_pack_enabled

from .serializers import AdminBiblePackChangeSerializer, AdminBiblePackSerializer, BiblePackSerializer

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


# --- Phase 34 Slice 8: the admin's Bible settings ---------------------------


class AdminBiblePackChangePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AdminBiblePackListView(generics.ListAPIView):
    """Every pack, hidden ones included, with its file details and flags."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminBiblePackSerializer
    pagination_class = BiblePackPagination

    def get_queryset(self):
        return selectors.list_all_packs()


class AdminBiblePackChangeListView(generics.ListAPIView):
    """Who changed what in the Bible settings, newest first."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminBiblePackChangeSerializer
    pagination_class = AdminBiblePackChangePagination

    def get_queryset(self):
        return selectors.list_pack_changes()


class _AdminBiblePackActionView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def act(self, request, code: str):  # pragma: no cover - overridden
        raise NotImplementedError

    def post(self, request, code: str):
        try:
            pack = self.act(request, code)
        except BiblePackChangeRefused as exc:
            http_status = status.HTTP_404_NOT_FOUND if exc.code == "not_found" else status.HTTP_400_BAD_REQUEST
            return Response({"code": exc.code, "message": str(exc)}, status=http_status)
        return Response(AdminBiblePackSerializer(pack).data)


class AdminBiblePackEnableView(_AdminBiblePackActionView):
    def act(self, request, code: str):
        return set_bible_pack_enabled(actor=request.user, code=code, enabled=True)


class AdminBiblePackDisableView(_AdminBiblePackActionView):
    def act(self, request, code: str):
        return set_bible_pack_enabled(actor=request.user, code=code, enabled=False)


class AdminBiblePackMakeDefaultView(_AdminBiblePackActionView):
    def act(self, request, code: str):
        return make_bible_pack_default(actor=request.user, code=code)
