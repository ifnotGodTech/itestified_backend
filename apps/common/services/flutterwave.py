from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


class FlutterwaveGatewayError(Exception):
    pass


@dataclass
class FlutterwaveInitResult:
    checkout_url: str
    provider_transaction_id: str = ""


@dataclass
class FlutterwaveVerifyResult:
    status: str
    provider_transaction_id: str
    status_reason: str = ""


@dataclass
class FlutterwavePlanResult:
    provider_plan_id: str


@dataclass
class FlutterwaveSubscriptionCancelResult:
    status: str


@dataclass
class FlutterwaveSubscriptionRecord:
    provider_subscription_id: str
    plan_id: str
    status: str


class FlutterwaveGateway:
    """Shared Flutterwave HTTP client -- originally built for one-off
    donation charges (Phase 5), extended for Payment Plans / recurring
    subscription charges (Phase 21). Lives in apps/common since it's now
    reused by two domains (apps.donations, apps.subscriptions) and is
    genuinely stable, generic transport, not business logic -- per
    AGENTS.md's "shared cross-cutting code belongs in apps/common/ only
    when it is truly reusable and stable"."""

    def __init__(self, secret_key: str, base_url: str):
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.secret_key}",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            raise FlutterwaveGatewayError("Unable to reach the payment gateway.") from exc

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(path, "POST", payload)

    def _get(self, path: str) -> dict[str, Any]:
        return self._request(path, "GET")

    def _put(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request(path, "PUT", payload or {})

    def initialize(
        self,
        *,
        amount: int,
        currency: str,
        tx_ref: str,
        customer_email: str,
        customer_name: str,
        redirect_url: str,
        payment_plan: str = "",
    ) -> FlutterwaveInitResult:
        # `amount` is in minor currency units (kobo/cents) per our internal convention,
        # but Flutterwave's payment-initialization API expects the major unit (naira/dollars).
        major_unit_amount = amount / 100
        payload: dict[str, Any] = {
            "tx_ref": tx_ref,
            "amount": f"{major_unit_amount:.2f}",
            "currency": currency,
            "redirect_url": redirect_url,
            "customer": {
                "email": customer_email,
                "name": customer_name or "iTestified Giver",
            },
            "customizations": {
                "title": "iTestified Giving",
                "description": "Donation payment",
            },
        }
        # A payment_plan-tagged charge is how Flutterwave subscribes the
        # customer: this same /v3/payments call becomes the first charge of
        # a recurring Payment Plan rather than a one-off charge.
        if payment_plan:
            payload["payment_plan"] = payment_plan
            payload["customizations"] = {
                "title": "iTestified Premium",
                "description": "Premium subscription payment",
            }
        response = self._post("/v3/payments", payload)
        data = response.get("data") or {}
        link = data.get("link")
        if not link:
            raise FlutterwaveGatewayError("Unable to initialize payment.")
        return FlutterwaveInitResult(
            checkout_url=link,
            provider_transaction_id=str(data.get("id") or ""),
        )

    def verify(self, transaction_id: str) -> FlutterwaveVerifyResult:
        response = self._get(f"/v3/transactions/{transaction_id}/verify")
        data = response.get("data") or {}
        status = str(data.get("status") or "").lower()
        if status == "successful":
            mapped_status = "successful"
        else:
            mapped_status = "declined"
        reason = str(data.get("processor_response") or data.get("narration") or "")
        return FlutterwaveVerifyResult(
            status=mapped_status,
            provider_transaction_id=str(data.get("id") or transaction_id),
            status_reason=reason,
        )

    def create_payment_plan(
        self,
        *,
        name: str,
        amount: int,
        currency: str,
        interval: str,
    ) -> FlutterwavePlanResult:
        # amount here is minor units too, converted the same way as initialize().
        major_unit_amount = amount / 100
        payload = {
            "amount": f"{major_unit_amount:.2f}",
            "name": name,
            "interval": interval,
            "currency": currency,
        }
        response = self._post("/v3/payment-plans", payload)
        data = response.get("data") or {}
        plan_id = data.get("id")
        if not plan_id:
            raise FlutterwaveGatewayError("Unable to create payment plan.")
        return FlutterwavePlanResult(provider_plan_id=str(plan_id))

    def cancel_subscription(self, provider_subscription_id: str) -> FlutterwaveSubscriptionCancelResult:
        response = self._put(f"/v3/subscriptions/{provider_subscription_id}/cancel")
        data = response.get("data") or {}
        status = str(data.get("status") or "cancelled").lower()
        return FlutterwaveSubscriptionCancelResult(status=status)

    def find_active_subscription_by_email(self, email: str) -> FlutterwaveSubscriptionRecord | None:
        """Looks up the Flutterwave-side subscription created by a
        successful payment_plan-tagged charge. Used right after a
        subscription's first charge succeeds, so we have a real
        provider_subscription_id to cancel later -- deliberately not
        relying on a webhook payload field for this, since the exact shape
        of that field isn't confirmed (see Phase 21 Slice 1's own note);
        GET /v3/subscriptions is a directly-documented, confirmed endpoint."""
        query = parse.urlencode({"email": email})
        response = self._get(f"/v3/subscriptions?{query}")
        rows = response.get("data") or []
        active = [row for row in rows if str(row.get("status", "")).lower() == "active"]
        candidates = active or rows
        if not candidates:
            return None
        # Most recent first, in case a user has more than one historical row.
        latest = sorted(candidates, key=lambda row: row.get("id", 0), reverse=True)[0]
        return FlutterwaveSubscriptionRecord(
            provider_subscription_id=str(latest.get("id") or ""),
            plan_id=str(latest.get("plan") or ""),
            status=str(latest.get("status") or ""),
        )
