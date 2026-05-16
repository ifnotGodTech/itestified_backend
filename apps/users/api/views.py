from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.users.choices import UserAccountStatus
from apps.users.models import Profile
from apps.users.models import User

from .serializers import AdminUserSerializer, ProfileSerializer


class CurrentProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(
            user=request.user,
            defaults={"full_name": request.user.email},
        )
        serializer = ProfileSerializer(profile)
        return Response(serializer.data)


class AdminUserPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AdminUserListView(generics.ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = AdminUserSerializer
    pagination_class = AdminUserPagination

    def get_queryset(self):
        queryset = User.objects.select_related("profile").order_by("-date_joined")
        status_filter = (self.request.query_params.get("status") or "").strip().lower()
        search_text = (self.request.query_params.get("q") or "").strip()
        if status_filter in {UserAccountStatus.ACTIVE, UserAccountStatus.DEACTIVATED, UserAccountStatus.DELETED}:
            queryset = queryset.filter(account_status=status_filter)
        if search_text:
            queryset = queryset.filter(email__icontains=search_text)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        users = page if page is not None else queryset
        payload = [
            {
                "id": user.id,
                "email": user.email,
                "full_name": (
                    user.profile.full_name
                    if hasattr(user, "profile") and user.profile.full_name
                    else user.email
                ),
                "account_status": user.account_status,
                "created_at": user.date_joined,
            }
            for user in users
        ]
        if page is not None:
            return self.get_paginated_response(payload)
        return Response(payload)


class AdminUserDetailView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request, user_id: int):
        user = User.objects.select_related("profile").filter(id=user_id).first()
        if user is None:
            return Response({"message": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "id": user.id,
                "email": user.email,
                "full_name": (
                    user.profile.full_name
                    if hasattr(user, "profile") and user.profile.full_name
                    else user.email
                ),
                "account_status": user.account_status,
                "created_at": user.date_joined,
            }
        )


class AdminUserDeactivateView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, user_id: int):
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return Response({"message": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.account_status == UserAccountStatus.DELETED:
            return Response({"message": "Deleted users cannot be deactivated."}, status=status.HTTP_400_BAD_REQUEST)
        if user.account_status != UserAccountStatus.DEACTIVATED:
            user.account_status = UserAccountStatus.DEACTIVATED
            user.save(update_fields=["account_status"])
        return Response({"id": user.id, "account_status": user.account_status})


class AdminUserReactivateView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, user_id: int):
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return Response({"message": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.account_status == UserAccountStatus.DELETED:
            return Response({"message": "Deleted users cannot be reactivated."}, status=status.HTTP_400_BAD_REQUEST)
        if user.account_status != UserAccountStatus.ACTIVE:
            user.account_status = UserAccountStatus.ACTIVE
            user.save(update_fields=["account_status"])
        return Response({"id": user.id, "account_status": user.account_status})
