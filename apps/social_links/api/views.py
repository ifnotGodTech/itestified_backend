from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.social_links.choices import SocialPlatform
from apps.social_links.models import SocialLink

from .serializers import SocialLinkSerializer


class AdminSocialLinkListView(APIView):
    """Returns the current config for every known platform, so the
    dashboard can render a row for each one even before it's ever been
    set -- same pattern as AdminAppVersionListView."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        existing = {item.platform: item for item in SocialLink.objects.all()}
        payload = []
        for platform, _label in SocialPlatform.choices:
            instance = existing.get(platform)
            if instance is not None:
                payload.append(SocialLinkSerializer(instance).data)
            else:
                payload.append(
                    {
                        "platform": platform,
                        "url": "",
                        "is_active": False,
                        "display_order": 0,
                        "updated_at": None,
                    }
                )
        return Response(payload, status=status.HTTP_200_OK)


class AdminSocialLinkUpdateView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def put(self, request, platform: str):
        if platform not in SocialPlatform.values:
            return Response({"message": "Unknown platform."}, status=status.HTTP_400_BAD_REQUEST)
        instance = SocialLink.objects.filter(platform=platform).first()
        serializer = SocialLinkSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(platform=platform, updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def mobile_social_links_view(request):
    """Public, unauthenticated -- powers the "Follow @iTestified" screen.
    Only returns platforms an admin has actually turned on with a real URL;
    a blank or deactivated row is indistinguishable from "not offered"."""
    links = SocialLink.objects.filter(is_active=True).exclude(url="")
    return Response({"result": SocialLinkSerializer(links, many=True).data}, status=status.HTTP_200_OK)
