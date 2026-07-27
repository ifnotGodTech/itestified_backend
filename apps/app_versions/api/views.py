from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin, IsSuperAdmin
from apps.app_versions.choices import AppPlatform
from apps.app_versions.models import AppVersionConfig

from .serializers import AppVersionConfigSerializer


class AdminAppVersionListView(APIView):
    """Returns the current minimum-version config for every platform, so
    the settings screen can render both rows even before either has ever
    been set."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin, IsSuperAdmin]

    def get(self, request):
        existing = {
            item.platform: item for item in AppVersionConfig.objects.all()
        }
        payload = []
        for platform, _label in AppPlatform.choices:
            instance = existing.get(platform)
            if instance is not None:
                payload.append(AppVersionConfigSerializer(instance).data)
            else:
                payload.append(
                    {
                        "platform": platform,
                        "minimum_version": "",
                        "latest_version": "",
                        "updated_at": None,
                    }
                )
        return Response(payload, status=status.HTTP_200_OK)


class AdminAppVersionUpdateView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin, IsSuperAdmin]

    def put(self, request, platform: str):
        if platform not in AppPlatform.values:
            return Response(
                {"message": "Unknown platform."}, status=status.HTTP_400_BAD_REQUEST
            )
        # Look up without creating: validate first, and only persist (create
        # or update) once the submitted version is actually valid, so a
        # rejected request never leaves a blank row behind.
        instance = AppVersionConfig.objects.filter(platform=platform).first()
        serializer = AppVersionConfigSerializer(
            instance, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(platform=platform, updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
