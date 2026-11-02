import json
from pathlib import Path

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures"

# Everything get_order may return. Anything else, at any level, is a leak.
ORDER_KEYS = {
    "order_id", "status", "ordered", "delivery_date", "delivery_from", "delivery_to", "home_delivery",
    "store", "item_count", "lines_total", "products_total", "offer_discount", "total", "items",
}
LINE_KEYS = {
    "product_id", "name", "brand", "size", "category", "section", "quantity", "unit_price", "line_total",
    "delivered", "delivered_quantity", "delivered_total", "offer", "plus_offer", "unavailable_reason",
    "replacement", "returns", "comment", "is_service",
}
RELATED_KEYS = {"product_id", "name", "brand", "size", "quantity", "unit_price", "line_total", "reason"}
FORBIDDEN_KEYS = {
    "recipient_name", "address", "zipCode", "city", "lat", "lng", "order_pickup_code", "doorcode", "door", "floor",
    "deliveryPointId", "deliveryPointText", "deliveryComment", "payments", "payment_solution", "uid", "tid",
    "transact", "receipt_content", "name_of_recipient", "phone", "pickupzone", "deliveryAddress",
}


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def server(load_server, monkeypatch):
    server = load_server(BILKATOGO_LOGIN_TOKEN="t")

    async def fake_jwt(force=False):
        return "jwt", "test"

    monkeypatch.setattr(server, "_get_jwt", fake_jwt)
    return server


def _serve(server, payload):
    server.requests = []

    def handler(request):
        server.requests.append(request)
        return httpx.Response(200, json=payload)

    server._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _order(server, name):
    data = _fixture(name)
    _serve(server, data)
    return await server.get_order(data["order"]["orderId"])


def _by_name(order):
    return {line["name"]: line for line in order["items"]}


# ---- the ordered order ----------------------------------------------------------------------------
async def test_every_line_is_returned_and_services_are_flagged(server):
    order = await _order(server, "order_ordered")
    assert [(line["name"], line["is_service"]) for line in order["items"]] == [
        ("Pakkeservice", True), ("Peberfrugter røde", False), ("Bananer", False),
        ("Cheerios", False), ("Yoghurt m. jordbær", False), ("Papirpose", True),
    ]


async def test_service_flag_follows_the_category_not_the_name(server):
    data = _fixture("order_ordered")
    packing = data["order"]["lines"][0]["lines"][0]["orderlines"][0]
    packing["product"]["name"] = "Noget helt andet"
    other = data["order"]["lines"][1]["lines"][0]["orderlines"][0]
    other["product"]["name"] = "Pakkeservice"
    _serve(server, data)
    lines = _by_name(await server.get_order("100000000001"))
    assert lines["Noget helt andet"]["is_service"] is True and lines["Pakkeservice"]["is_service"] is False


async def test_unit_price_is_the_price_paid_with_offers_applied(server):
    lines = _by_name(await _order(server, "order_ordered"))
    yoghurt = lines["Yoghurt m. jordbær"]  # shelf price 15.00, paid 10.00 with the member price
    assert (yoghurt["unit_price"], yoghurt["line_total"]) == (10.0, 10.0)
    assert (yoghurt["offer"], yoghurt["plus_offer"]) == ("Skarp pris", "Plus pris 10,00")
    bananas = lines["Bananer"]
    assert (bananas["quantity"], bananas["unit_price"], bananas["line_total"]) == (10, 2.5, 25.0)
    assert (bananas["size"], bananas["offer"], bananas["product_id"]) == ("1 stk", "Mix 10 for 25,00", 900003)


async def test_details_of_a_line(server):
    cheerios = _by_name(await _order(server, "order_ordered"))["Cheerios"]
    assert (cheerios["brand"], cheerios["size"], cheerios["offer"]) == ("Nestlé", "375 g", None)  # "Se Her" dropped
    assert cheerios["category"] == "Kolonial > Morgenmad > Morgenmadsprodukter"
    assert (cheerios["section"], cheerios["comment"], cheerios["replacement"], cheerios["returns"]) == ("Kolonial", None, None, [])


async def test_summary_of_an_ordered_order(server):
    order = await _order(server, "order_ordered")
    assert (order["order_id"], order["status"], order["ordered"]) == ("100000000001", "Bestilt", "2026-10-31 14:00:00")
    assert (order["delivery_date"], order["delivery_from"], order["delivery_to"]) == ("2026-11-01", "10:00:00", "12:00:00")
    assert (order["store"], order["home_delivery"], order["item_count"]) == ("Bilka Testby", False, 13)
    assert (order["total"], order["products_total"], order["offer_discount"]) == (122.95, 78.95, 2.5)
    assert order["lines_total"] == 122.95  # nothing was struck, so the order is as placed
    assert all(line["delivered"] and line["delivered_total"] == line["line_total"] for line in order["items"])
    assert "items_preview" not in order


# ---- the invoiced order: lines the shop could not deliver ------------------------------------------
async def test_a_sold_out_line_is_kept_as_ordered_but_not_delivered(server):
    milk = _by_name(await _order(server, "order_invoiced"))["Letmælk"]
    # The shop keeps the ordered quantity and amount and only strikes the line through.
    assert (milk["quantity"], milk["unit_price"], milk["line_total"]) == (2, 10.0, 20.0)
    assert (milk["delivered"], milk["delivered_quantity"], milk["delivered_total"]) == (False, 0, 0.0)
    assert milk["unavailable_reason"] == "udsolgt"  # the shop's tagline
    assert milk["replacement"] is None


async def test_a_delivered_line_is_delivered_in_full(server):
    pasta = _by_name(await _order(server, "order_invoiced"))["Spaghetti"]
    assert (pasta["delivered"], pasta["delivered_quantity"], pasta["delivered_total"]) == (True, 1, 4.95)
    assert pasta["unavailable_reason"] is None


async def test_a_replaced_line_shows_what_came_instead(server):
    cola = _by_name(await _order(server, "order_invoiced"))["Cola"]
    assert (cola["delivered"], cola["delivered_total"], cola["unavailable_reason"]) == (False, 0.0, "Erstattet med")
    assert cola["replacement"] == {
        "product_id": 900013, "name": "Pepsi", "brand": "Pepsi", "size": "1.5 l", "quantity": 1,
        "unit_price": 14.0, "line_total": 14.0, "reason": None,
    }


async def test_returns_and_comment_are_shown(server):
    bread = _by_name(await _order(server, "order_invoiced"))["Rugbrød"]
    assert bread["comment"] == "Uden kerner"
    assert [(r["name"], r["quantity"], r["line_total"], r["reason"]) for r in bread["returns"]] == [
        ("Rugbrød", 1, 15.0, "Beskadiget")
    ]


async def test_summary_of_an_invoiced_order(server):
    order = await _order(server, "order_invoiced")
    assert (order["status"], order["total"], order["products_total"], order["item_count"]) == ("Faktureret", 77.95, 33.95, 3)
    assert order["lines_total"] == 125.95  # what was originally ordered, struck lines included


def _delivered(order):
    """What was actually delivered: the delivered lines plus the replacements that took the place of others."""
    replacements = [line["replacement"] for line in order["items"] if line["replacement"]]
    money = sum(line["delivered_total"] for line in order["items"]) + sum(r["line_total"] for r in replacements)
    units = sum(line["delivered_quantity"] for line in order["items"] if not line["is_service"])
    return round(money, 2), units + sum(r["quantity"] for r in replacements)


@pytest.mark.parametrize("name", ["order_ordered", "order_invoiced"])
async def test_delivered_lines_add_up_to_the_invoiced_total_and_item_count(server, name):
    # The same two sums hold on a real invoiced order: its lines add up to 678.39 as ordered, 647.44 as
    # delivered (the invoiced total), and 37 units as ordered against the invoiced 34.
    order = await _order(server, name)
    money, units = _delivered(order)
    assert (money, units) == (order["total"], order["item_count"])


# ---- privacy ---------------------------------------------------------------------------------------
def _walk(value):
    """Every key and every string value anywhere inside `value`."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield "key", key
            yield from _walk(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _walk(inner)
    elif isinstance(value, str):
        yield "value", value


@pytest.mark.parametrize("name", ["order_ordered", "order_invoiced"])
async def test_nothing_personal_reaches_the_output(server, name):
    secrets = {text for kind, text in _walk(_fixture(name)) if kind == "value" and text.startswith("REDACTED-")}
    assert len(secrets) >= 10  # the fixture really contains what this test looks for
    order = await _order(server, name)
    dumped = json.dumps(order, ensure_ascii=False)
    assert [s for s in secrets if s in dumped] == []
    assert {text for kind, text in _walk(order) if kind == "key"}.isdisjoint(FORBIDDEN_KEYS)


@pytest.mark.parametrize("name", ["order_ordered", "order_invoiced"])
async def test_only_whitelisted_fields_are_returned(server, name):
    order = await _order(server, name)
    assert set(order) == ORDER_KEYS
    for line in order["items"]:
        assert set(line) == LINE_KEYS
        assert all(set(r) == RELATED_KEYS for r in [line["replacement"], *line["returns"]] if r)


async def test_a_replacement_in_an_unexpected_shape_still_leaks_nothing(server):
    data = _fixture("order_invoiced")
    cola = data["order"]["lines"][3]["lines"][0]["orderlines"][0]
    cola["replacement"] = {"product": {"objectID": 5, "name": "Pepsi", "doorcode": "REDACTED-X"}, "doorcode": "REDACTED-Y"}
    spaghetti = data["order"]["lines"][1]["lines"][0]["orderlines"][0]
    spaghetti["returns"] = ["Kunden fortrød REDACTED-PHONE"]
    _serve(server, data)
    order = await server.get_order("100000000002")
    lines = _by_name(order)
    assert set(lines["Cola"]["replacement"]) == RELATED_KEYS and lines["Cola"]["replacement"]["name"] == "Pepsi"
    assert "REDACTED-X" not in json.dumps(order) and "REDACTED-Y" not in json.dumps(order)
    assert lines["Spaghetti"]["returns"] == [{"reason": "Kunden fortrød REDACTED-PHONE"}]  # a bare text is kept, nothing else


# ---- requests and errors --------------------------------------------------------------------------
async def test_get_order_asks_for_the_right_order(server):
    await _order(server, "order_ordered")
    assert server.requests[0].url.params["orderId"] == "100000000001"
    assert server.requests[0].url.path.endswith("/v7/OrderDetails")


async def test_a_number_works_as_order_id_too(server):
    _serve(server, _fixture("order_ordered"))
    assert (await server.get_order(100000000001))["order_id"] == "100000000001"


@pytest.mark.parametrize("bad", ["", "abc", "1 OR 1", "12", "../../x", "1" * 21])
async def test_get_order_rejects_odd_ids_without_a_request(server, bad):
    _serve(server, _fixture("order_ordered"))
    with pytest.raises(ToolError, match="order_id"):
        await server.get_order(bad)
    assert not server.requests


async def test_unknown_order_is_reported_not_treated_as_a_login_problem(server):
    # The shop answers with msg and code but *your* uid, so this is not an expired session.
    _serve(server, {"msg": "Ordren kunne ikke findes.", "code": None, "eid": 404, "uid": 42})
    with pytest.raises(ToolError, match="list_orders") as error:  # says what to do next
        await server.get_order("100000000099")
    assert "kunne ikke findes" in str(error.value)  # and keeps what the shop said
    assert len(server.requests) == 1  # no pointless second attempt with a fresh login


async def test_logged_out_answer_is_still_a_login_problem(server):
    _serve(server, {"msg": "Not authenticated", "code": "X", "eid": 401, "uid": -1})
    with pytest.raises(server.AuthError):
        await server.get_order("100000000001")
    assert len(server.requests) == 2  # retried once with a fresh login
