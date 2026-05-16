from django.db import connections
from django.db.utils import OperationalError
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        database_status = "ok"

        try:
            connections["default"].cursor()
        except OperationalError:
            database_status = "error"

        return Response(
            {
                "status": "ok" if database_status == "ok" else "degraded",
                "checks": {
                    "database": database_status,
                },
            }
        )
