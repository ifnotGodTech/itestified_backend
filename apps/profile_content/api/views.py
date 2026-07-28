from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.profile_content.choices import ProfileContentKey
from apps.profile_content.models import ProfileContentBlock

from .serializers import ProfileContentBlockSerializer


class AdminProfileContentBlockListView(APIView):
    """Returns the current body for every known content key, so the
    dashboard can render a row for each one even before it's ever been
    edited -- same pattern as AdminSocialLinkListView."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        existing = {item.key: item for item in ProfileContentBlock.objects.all()}
        payload = []
        for key, _label in ProfileContentKey.choices:
            instance = existing.get(key)
            if instance is not None:
                payload.append(ProfileContentBlockSerializer(instance).data)
            else:
                payload.append({"key": key, "body": "", "updated_at": None})
        return Response(payload, status=status.HTTP_200_OK)


class AdminProfileContentBlockUpdateView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def put(self, request, key: str):
        if key not in ProfileContentKey.values:
            return Response({"message": "Unknown content key."}, status=status.HTTP_400_BAD_REQUEST)
        instance = ProfileContentBlock.objects.filter(key=key).first()
        serializer = ProfileContentBlockSerializer(instance, data=request.data, partial=True, context={"key": key})
        serializer.is_valid(raise_exception=True)
        serializer.save(key=key, updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def mobile_profile_content_blocks_view(request):
    """Public, unauthenticated -- powers the About Us / Terms of Use /
    Privacy Policy screens plus the Help screen's support email/phone.
    Always returns every known key (blank if an admin has somehow cleared
    one) so mobile never has to guess which keys exist."""
    existing = {item.key: item.body for item in ProfileContentBlock.objects.all()}
    result = {key: existing.get(key, "") for key, _label in ProfileContentKey.choices}
    return Response({"result": result}, status=status.HTTP_200_OK)
