"""Price anchors from the Azure Retail Prices API.

The API is public and unauthenticated, which makes it the only provider whose
prices we can record programmatically without an account. It is used strictly as
an **anchor**: the simulator's price table stays an explicit input, and the
report states that prices are modelled, not quoted.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API = "https://prices.azure.com/api/retail/prices"
REFERENCE_SKUS = {
    "Standard_D2s_v5": 2,
    "Standard_D4s_v5": 4,
    "Standard_D8s_v5": 8,
}


def _query(filter_expression: str, max_pages: int = 3) -> list[dict[str, Any]]:
    url = f"{API}?$filter={urllib.parse.quote(filter_expression)}"
    items: list[dict[str, Any]] = []
    for _ in range(max_pages):
        request = urllib.request.Request(url, headers={"User-Agent": "spothedge/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        items.extend(payload.get("Items", []))
        next_page = payload.get("NextPageLink")
        if not next_page:
            break
        url = next_page
    return items


def _is_linux_vm(item: dict[str, Any]) -> bool:
    product = str(item.get("productName", ""))
    return "Virtual Machines" in product and "Windows" not in product


def _is_spot(item: dict[str, Any]) -> bool:
    text = f"{item.get('skuName', '')} {item.get('meterName', '')}".lower()
    return "spot" in text


def _is_low_priority(item: dict[str, Any]) -> bool:
    """Low Priority meters are a legacy eviction product, not standard on-demand."""

    text = f"{item.get('skuName', '')} {item.get('meterName', '')}".lower()
    return "low priority" in text


def fetch_prices(region: str = "eastus") -> dict[str, Any]:
    references: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []

    for arm_sku, vcpu in REFERENCE_SKUS.items():
        expression = (
            "serviceName eq 'Virtual Machines' "
            f"and armRegionName eq '{region}' "
            "and priceType eq 'Consumption' "
            f"and armSkuName eq '{arm_sku}'"
        )
        items = [item for item in _query(expression) if _is_linux_vm(item)]
        raw.extend(items)

        on_demand = [i for i in items if not _is_spot(i) and not _is_low_priority(i)]
        spot = [i for i in items if _is_spot(i)]
        od_price = float(on_demand[0]["retailPrice"]) if on_demand else None
        spot_price = float(spot[0]["retailPrice"]) if spot else None
        discount = None
        if od_price and spot_price and od_price > 0:
            discount = 1.0 - spot_price / od_price

        references.append(
            {
                "armSkuName": arm_sku,
                "vcpu": vcpu,
                "onDemandUsdPerHour": od_price,
                "spotUsdPerHour": spot_price,
                "impliedSpotDiscount": discount,
                "onDemandUsdPerVcpuHour": (od_price / vcpu) if od_price else None,
                "spotUsdPerVcpuHour": (spot_price / vcpu) if spot_price else None,
            }
        )

    per_vcpu = [
        ref["onDemandUsdPerVcpuHour"]
        for ref in references
        if ref["onDemandUsdPerVcpuHour"] is not None
    ]
    median_anchor = sorted(per_vcpu)[len(per_vcpu) // 2] if per_vcpu else None

    return {
        "source": API,
        "region": region,
        "fetchedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": "USD",
        "referenceSkus": references,
        "medianOnDemandUsdPerVcpuHour": median_anchor,
        "items": [
            {
                "skuName": item.get("skuName"),
                "armSkuName": item.get("armSkuName"),
                "productName": item.get("productName"),
                "meterName": item.get("meterName"),
                "retailPrice": item.get("retailPrice"),
                "unitOfMeasure": item.get("unitOfMeasure"),
                "armRegionName": item.get("armRegionName"),
                "priceType": item.get("priceType"),
            }
            for item in raw[:200]
        ],
        "notes": (
            "Anchors only. The simulator's price table is an explicit input; "
            "no figure here is a quote for a specific workload or commitment."
        ),
    }


def write_price_file(anchors: dict[str, Any], out: Path, base_on_demand: float) -> None:
    payload = dict(anchors)
    payload["modelAssumption"] = {
        "onDemandUsdPerVcpuHour": base_on_demand,
        "role": "base assumption from the proposal; anchors above are for cross-checking",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
