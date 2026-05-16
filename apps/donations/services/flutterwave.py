import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request


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


class FlutterwaveGateway:
    def __init__(self, secret_key: str, base_url: str):
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.secret_key}",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            raise FlutterwaveGatewayError("Unable to initialize payment.") from exc

    def _get(self, path: str) -> dict[str, Any]:
        req = request.Request(
            f"{self.base_url}{path}",
            method="GET",
            headers={"Authorization": f"Bearer {self.secret_key}"},
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            raise FlutterwaveGatewayError("Unable to verify payment.") from exc

    def initialize(
        self,
        *,
        amount: int,
        currency: str,
        tx_ref: str,
        customer_email: str,
        customer_name: str,
        redirect_url: str,
    ) -> FlutterwaveInitResult:
        payload = {
            "tx_ref": tx_ref,
            "amount": str(amount),
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
