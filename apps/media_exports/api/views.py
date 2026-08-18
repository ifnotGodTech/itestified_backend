import logging

from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.testimonies.models import TestimonyStatus

from ..models import BrandedVideoExport, BrandedVideoExportStatus
from ..services import MediaExportError, get_branding_config, request_branded_video_export
from .serializers import BrandedVideoExportSerializer, MediaExportBrandingConfigSerializer

logger = logging.getLogger(__name__)


class MobileBrandedVideoExportView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, testimony_id: int):
        try:
            export = request_branded_video_export(testimony_id=testimony_id, requested_by=request.user)
        except MediaExportError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:  # noqa: BLE001 - keep infrastructure failures JSON and observable.
            logger.exception("Unexpected branded export request failure for testimony %s", testimony_id)
            return Response(
                {"message": "Branded video export is temporarily unavailable. Please try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(BrandedVideoExportSerializer(export).data, status=status.HTTP_202_ACCEPTED)

    def get(self, request, testimony_id: int):
        export = (
            BrandedVideoExport.objects.filter(
                testimony_id=testimony_id,
                testimony__status=TestimonyStatus.APPROVED,
            )
            .order_by("-branding_version", "-created_at")
            .first()
        )
        if export is None:
            return Response({"message": "No branded export has been requested."}, status=status.HTTP_404_NOT_FOUND)
        return Response(BrandedVideoExportSerializer(export).data, status=status.HTTP_200_OK)


class ExportPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AdminMediaExportBrandingView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        return Response(MediaExportBrandingConfigSerializer(get_branding_config()).data)

    def put(self, request):
        config = get_branding_config()
        serializer = MediaExportBrandingConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        config = serializer.save(updated_by=request.user)
        return Response(MediaExportBrandingConfigSerializer(config).data)


class AdminBrandedVideoExportListView(generics.ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = BrandedVideoExportSerializer
    pagination_class = ExportPagination

    def get_queryset(self):
        queryset = BrandedVideoExport.objects.select_related("testimony").order_by("-updated_at")
        status_filter = self.request.query_params.get("status")
        if status_filter in BrandedVideoExportStatus.values:
            queryset = queryset.filter(status=status_filter)
        return queryset
