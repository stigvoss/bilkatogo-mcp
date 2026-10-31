import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

pytestmark = pytest.mark.anyio


def _line(name, quantity, unit, amount, product=None, **extra):
    return {
        "orderlines": [
            {
                "quantity": quantity,
                "amount": amount,
                "unitprice": unit,
                "product": {"objectID": 1000 + len(name), "name": name, "cpOffer": False, **(product or {})},
                "unavailable_reason": "",
                "replacement": None,
                **extra,
            }
        ]
    }


# Same structure as the shop's OrderDetails answer, with invented values. Everything marked SECRET
# must never reach the model.
ORDER_DETAILS = {
    "order": {
        "orderId": "100000000001",
        "status": "Bestilt",
        "price": 12345,
        "stat": {
            "price": 12345,
            "prod_price": 11445,
            "promo": 250,
            "specifications": [
                {"text": "Pakkeservice", "value": 400},
                {"text": "Emballage", "value": 500},
                {"text": "Levering", "value": 0},
            ],
        },
        "deliveryDate": "2026-11-01",
        "deliveryInterval": {"start": "10:00:00", "end": "12:00:00"},
        "ordered": {"channel": "Web", "date": "2026-10-31", "time": "14:00:00"},
        "totalProductAmount": 12,
        "deliveryAddress": {
            "location": "Bilka Testby",
            "address": "SECRET STREET 1",
            "zipCode": "SECRET",
            "order_pickup_code": "SECRET",
            "lat": "SECRET",
            "lng": "SECRET",
            "recipient_name": "SECRET",
            "doorcode": "SECRET",
            "home_delivery": False,
        },
        "name": "SECRET NAME",
        "address": "SECRET STREET 1",
        "receipt_content": {"pickup_body": "SECRET"},
        "payments": [{"providerId": "nets", "amount": 12345}],
        "lines": [
            {"headline": "Services", "lines": [_line("Pakkeservice", 1, 400, 400)]},
            {
                "headline": "Frugt & grønt",
                "lines": [
                    _line(
                        "Bananer", 10, 250, 2500,
                        {"units": 1, "unitsOfMeasure": "stk", "msg": "Mix 10 for 25,00",
                         "categories": {"lvl0": ["Frugt og grønt"], "lvl1": ["Frugt og grønt > Frugt"],
                                        "lvl2": ["Frugt og grønt > Frugt > Banan"]}},
                    )
                ],
            },
            {
                "headline": "Mejeri & køl",
                "lines": [
                    _line("Yoghurt", 1, 1500, 1500,
                          {"brand": "Yoggi", "units": 1.06, "unitsOfMeasure": "kg", "msg": "Skarp pris",
                           "cpOffer": True, "cpOfferMsg": "Plus pris 10,00",
                           "categories": {"lvl0": ["Mejeri"]}}),
                    _line("Cheerios", 1, 3495, 3495,
                          {"brand": "Nestlé", "units": 375, "unitsOfMeasure": "g", "msg": "Se Her"}),
                    _line("Mælk", 2, 1000, 2000, replacement={"name": "Anden mælk"}, unavailable_reason="Udgået"),
                ],
            },
            {"headline": "Emballage", "lines": [_line("Papirpose", 1, 500, 500)]},
        ],
    },
    "eid": -1,
    "uid": 42,
    "tid": "SECRET",
}


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


async def test_get_order_lists_what_was_bought(server):
    _serve(server, ORDER_DETAILS)
    order = await server.get_order("100000000001")
    assert [item["name"] for item in order["items"]] == ["Bananer", "Yoghurt", "Cheerios", "Mælk"]
    bananas = order["items"][0]
    assert (bananas["quantity"], bananas["unit_price"], bananas["line_total"]) == (10, 2.5, 25.0)
    assert (bananas["size"], bananas["offer"]) == ("1 stk", "Mix 10 for 25,00")
    assert bananas["category"] == "Frugt og grønt > Frugt > Banan" and bananas["section"] == "Frugt & grønt"
    yoghurt = order["items"][1]
    assert (yoghurt["brand"], yoghurt["size"], yoghurt["offer"], yoghurt["plus_offer"]) == (
        "Yoggi", "1.06 kg", "Skarp pris", "Plus pris 10,00"
    )
    assert order["items"][2]["offer"] is None  # the placeholder "Se Her" is dropped
    milk = order["items"][3]
    assert milk["replaced"] is True and milk["unavailable_reason"] == "Udgået"


async def test_get_order_separates_fees_and_totals(server):
    _serve(server, ORDER_DETAILS)
    order = await server.get_order(100000000001)  # a number works too
    assert order["fees"] == [{"name": "Pakkeservice", "amount": 4.0}, {"name": "Emballage", "amount": 5.0}]
    assert (order["products_total"], order["offer_discount"], order["total"]) == (114.45, 2.5, 123.45)
    assert (order["status"], order["item_count"], order["ordered"]) == ("Bestilt", 12, "2026-10-31 14:00:00")
    assert (order["delivery_date"], order["delivery_from"], order["store"]) == ("2026-11-01", "10:00:00", "Bilka Testby")
    assert not any(item["name"] in ("Pakkeservice", "Papirpose") for item in order["items"])


async def test_get_order_leaks_no_personal_data(server):
    _serve(server, ORDER_DETAILS)
    assert "SECRET" not in str(await server.get_order("100000000001"))


async def test_get_order_asks_for_the_right_order(server):
    _serve(server, ORDER_DETAILS)
    await server.get_order("100000000001")
    assert server.requests[0].url.params["orderId"] == "100000000001"
    assert server.requests[0].url.path.endswith("/v7/OrderDetails")


@pytest.mark.parametrize("bad", ["", "abc", "1 OR 1", "12", "../../x"])
async def test_get_order_rejects_odd_ids(server, bad):
    _serve(server, ORDER_DETAILS)
    with pytest.raises(ToolError, match="order_id"):
        await server.get_order(bad)
    assert not server.requests


async def test_unknown_order_is_reported_not_treated_as_a_login_problem(server):
    # The shop answers with msg and code but *your* uid, so this is not an expired session.
    _serve(server, {"msg": "Ordren kunne ikke findes.", "code": None, "eid": 404, "uid": 42})
    with pytest.raises(ToolError, match="kunne ikke findes"):
        await server.get_order("100000000099")
    assert len(server.requests) == 1  # no pointless second attempt with a fresh login


async def test_logged_out_answer_is_still_a_login_problem(server):
    _serve(server, {"msg": "Not authenticated", "code": "X", "eid": 401, "uid": -1})
    with pytest.raises(server.AuthError):
        await server.get_order("100000000001")
    assert len(server.requests) == 2  # retried once with a fresh login
