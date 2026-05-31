from __future__ import annotations

from typing import Any

from ..httpreq import Requester


class BillingAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def request_payment_link(self, redirect_url: str, plan: str, billing_period: str) -> str | None:
        result = await self.requester.request("billingRequestPaymentLink", {
            "redirectUrl": redirect_url,
            "plan": plan,
            "billingPeriod": billing_period,
        })
        return result["paymentLink"].get("url")

    async def cancel_subscription(self) -> dict[str, Any]:
        result = await self.requester.request("billingCancelSubscription", {})
        return result.get("subscription", {})

    async def get_subscription(self) -> dict[str, Any]:
        result = await self.requester.request("billingGetSubscription", {})
        return result["subscription"]
