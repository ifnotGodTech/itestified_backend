from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import Profile

from .serializers import ProfileSerializer


class CurrentProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(
            user=request.user,
            defaults={"full_name": request.user.email},
        )
        serializer = ProfileSerializer(profile)
        return Response(serializer.data)
