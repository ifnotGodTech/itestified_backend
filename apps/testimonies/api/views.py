from rest_framework import generics
from rest_framework.authentication import TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyFavorite, TestimonyStatus

from .serializers import (
    FavoriteSerializer,
    TestimonyCategorySerializer,
    TestimonyCreateSerializer,
    TestimonyDetailSerializer,
    TestimonyListSerializer,
    TestimonyVideoCreateSerializer,
)


class TestimonyPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class PublicCategoryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = TestimonyCategorySerializer
    queryset = TestimonyCategory.objects.filter(is_active=True).order_by("name")


class PublicTestimonyListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = TestimonyListSerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        queryset = Testimony.objects.select_related("author", "author__profile", "category").filter(
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        )
        category_slug = (self.request.query_params.get("category") or "").strip()
        search_text = (self.request.query_params.get("search") or "").strip()
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        if search_text:
            queryset = queryset.filter(title__icontains=search_text)
        return queryset


class PublicTestimonyDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = TestimonyDetailSerializer

    def get_queryset(self):
        return Testimony.objects.select_related("author", "author__profile", "category").filter(
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        )


class AuthenticatedWrittenTestimonyCreateView(generics.CreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TestimonyCreateSerializer


class AuthenticatedVideoTestimonyCreateView(generics.CreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TestimonyVideoCreateSerializer


class AuthenticatedMyTestimonyListView(generics.ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TestimonyDetailSerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        return Testimony.objects.select_related("author", "author__profile", "category").filter(
            author=self.request.user
        )


class FavoriteListView(generics.ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = FavoriteSerializer
    pagination_class = None

    def get_queryset(self):
        return TestimonyFavorite.objects.filter(user=self.request.user).order_by("-created_at")


class FavoriteToggleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(
            id=testimony_id,
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        ).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        TestimonyFavorite.objects.get_or_create(user=request.user, testimony=testimony)
        return Response({"message": "Added to favorites."}, status=status.HTTP_201_CREATED)

    def delete(self, request, testimony_id: int):
        TestimonyFavorite.objects.filter(user=request.user, testimony_id=testimony_id).delete()
        return Response({"message": "Removed from favorites."}, status=status.HTTP_200_OK)
