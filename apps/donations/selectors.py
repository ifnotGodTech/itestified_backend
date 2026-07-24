from typing import Any, Dict, List

from django.db.models import QuerySet, Sum

from apps.donations.models import Donation


def get_donation_totals_by_currency(queryset: "QuerySet[Donation]") -> List[Dict[str, Any]]:
    return list(
        queryset.values("currency").annotate(total_amount=Sum("amount")).order_by("currency")
    )
