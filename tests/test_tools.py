import pytest
from mcp.server.mcpserver.exceptions import ToolError

pytestmark = pytest.mark.anyio

ORDER = {
    "orderId": "1",
    "status": "Faktureret",
    "deliveryDate": "2026-05-03",
    "deliveryInterval": {"start": "14:00:00", "end": "16:00:00"},
    "ordered": {"date": "2026-05-03"},
    "totalProductAmount": 41,
    "orderedPrice": 79148,
    "packedPrice": 78723,
    "delivered": True,
    "content": "Rugbrød, ost",
    "name": "SECRET NAME",
    "address": "SECRET STREET",
    "zipcity": "SECRET",
    "pickupzone": {
        "location": "Bilka X",
        "home_delivery": False,
        "doorcode": "SECRET",
        "order_pickup_code": "SECRET",
        "lat": "1",
        "lng": "2",
        "recipient_name": "SECRET",
    },
}


@pytest.fixture
def server(load_server, monkeypatch):
    server = load_server(BILKATOGO_LOGIN_TOKEN="t", BILKATOGO_MAX_QUANTITY="20")
    server.calls = []

    async def fake_shop(path, params=None):
        server.calls.append((path, params))
        if path == "v7/OrderHistory":
            return {"total": 1, "orders": [ORDER]}
        if path == "v3/GetDeliveryDate":
            return {"deliveryDate": "2026-05-05", "intervalStart": "18:00", "uid": 123, "tid": "SECRET"}
        if path == "v6/Cart":
            return {"lines": []}
        return {"productId": 1, "productAmount": params["count"], "unitCount": 1, "sum": 100}

    monkeypatch.setattr(server, "_shop", fake_shop)
    return server


async def test_orders_are_trimmed_to_non_personal_fields(server):
    result = await server.list_orders()
    assert "SECRET" not in str(result)
    order = result["orders"][0]
    assert order["ordered_price"] == 791.48
    assert order["store"] == "Bilka X"


async def test_order_paging_is_clamped(server):
    await server.list_orders(limit=500, offset=-3)
    params = server.calls[-1][1]
    assert (params["limit"], params["offset"]) == (20, 0)


async def test_delivery_date_has_no_ids(server):
    result = await server.get_delivery_date()
    assert "SECRET" not in str(result)
    assert result["deliveryDate"] == "2026-05-05"


@pytest.mark.parametrize("quantity", [21, -1])
async def test_set_quantity_out_of_range_is_rejected(server, quantity):
    with pytest.raises(ToolError):
        await server.set_cart_quantity(1, quantity)


async def test_add_to_cart_over_the_cap_is_rejected(server):
    with pytest.raises(ToolError):
        await server.add_to_cart(1, 500)


async def test_quantity_at_the_cap_is_allowed(server):
    result = await server.set_cart_quantity(1, 20)
    assert result["quantity"] == 20
