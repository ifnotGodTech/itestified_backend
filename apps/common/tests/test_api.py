from django.test import TestCase
from django.urls import reverse


class HealthCheckViewTests(TestCase):
    def test_health_endpoint_returns_ok(self) -> None:
        response = self.client.get(reverse("health-check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["checks"]["database"], "ok")
