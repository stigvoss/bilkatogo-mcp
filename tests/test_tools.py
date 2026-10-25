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


CART = {
    "lines": [
        {
            "lines": [
                {
                    "orderlines": [
                        {
                            "product": {"id": 85465, "name": "Finvalsede havregryn"},
                            "quantity": 2,
                            "unitprice": 795,
                            "amount": 1590,
                        },
                        {
                            "product": {"id": 111, "name": "Ukendt vare"},
                            "quantity": 1,
                            "unitprice": 1000,
                            "amount": 1000,
                        },
                    ]
                }
            ]
        }
    ],
    "stat": {"price": 2590},
}


def _index(handler):
    import httpx

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def cart_server(server, monkeypatch):
    async def fake_shop(path, params=None):
        return CART

    monkeypatch.setattr(server, "_shop", fake_shop)
    return server


async def test_cart_lines_include_size_and_brand(cart_server):
    import httpx

    seen = {}

    def handler(request):
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "results": [
                    None,  # object id 111 sorts first and is unknown to the index
                    {
                        "brand": "Salling",
                        "netcontent": "1 kg",
                        "unitOfMeasurePrice": 795,
                        "unitOfMeasurePriceUnits": "Kg.",
                        "deepestCategoryPath": "Kolonial > Havregryn",
                    },
                ]
            },
        )

    cart_server._client = _index(handler)
    cart = await cart_server.get_cart()
    oats, unknown = cart["lines"]
    assert (oats["size"], oats["brand"], oats["price_per_unit"], oats["unit"]) == ("1 kg", "Salling", 7.95, "Kg.")
    assert oats["category"] == "Kolonial > Havregryn"
    assert "size" not in unknown
    assert seen["body"].count("objectID") == 2  # one batched request for the whole cart


async def test_cart_still_works_when_the_index_is_down(cart_server):
    import httpx

    cart_server._client = _index(lambda request: httpx.Response(503))
    cart = await cart_server.get_cart()
    assert [line["name"] for line in cart["lines"]] == ["Finvalsede havregryn", "Ukendt vare"]
    assert all("size" not in line for line in cart["lines"])
    assert cart["total"] == 25.9


# Real index hits, trimmed to the fields that matter for offers. Prices are in øre; store 1666.
def _hit(**fields):
    base = {
        "id": "1",
        "name": "Vare",
        "price": 1000,
        "sales_price": 1000,
        "is_multibuy": False,
        "multibuy_offer_description": "",
        "isInOffer": [],
        "cpOffer": False,
        "cpOfferTitle": "",
        "cpOfferPrice": 0,
        "cpOfferAmount": 0,
        "cpPercentDiscount": 0,
        "cpOfferFromDate": "",
        "cpOfferToDate": "",
    }
    return {**base, **fields}


STORES = [1651, 1661, 1666, 1669]


def test_plus_offer_shows_the_member_price_and_dates(server):
    product = server._product(
        _hit(
            name="Ananas", price=2800, sales_price=2800, isInOffer=STORES, cpOffer=True,
            cpOfferTitle="Salling Princip ananas", cpOfferPrice=2200, cpOfferAmount=1,
            cpPercentDiscount=21, cpOfferFromDate="2026-10-23", cpOfferToDate="2026-11-06",
        )
    )
    assert product["on_offer"] is True
    assert product["offer"] == "Salling Princip ananas"
    assert product["price"] == 28.0 and product["regular_price"] is None
    assert product["plus_offer"] == {
        "title": "Salling Princip ananas", "price": 22.0, "amount": 1, "saving": 6.0, "percent_off": 21,
        "valid_from": "2026-10-23", "valid_to": "2026-11-06",
    }


def test_price_cut_shows_the_regular_price(server):
    product = server._product(
        _hit(name="Frilandsæg", price=4095, sales_price=2500, multibuy_offer_description="Skarp pris", isInOffer=STORES)
    )
    assert (product["price"], product["regular_price"]) == (25.0, 40.95)
    assert product["offer"] == "Skarp pris" and product["plus_offer"] is None


def test_multibuy_uses_the_mix_text(server):
    product = server._product(
        _hit(name="Vådservietter", price=1200, sales_price=1200, is_multibuy=True,
             multibuy_offer_description="Mix 16 for 139,00", isInOffer=STORES)
    )
    assert product["on_offer"] is True and product["offer"] == "Mix 16 for 139,00"


def test_plus_offer_title_beats_junk_multibuy_text(server):
    product = server._product(
        _hit(price=10900, sales_price=9900, multibuy_offer_description="Se Her", isInOffer=STORES,
             cpOffer=True, cpOfferTitle="Brystfilet eller inderfilet", cpOfferPrice=8500, cpOfferAmount=1)
    )
    assert product["offer"] == "Brystfilet eller inderfilet"
    assert product["plus_offer"]["price"] == 85.0
    assert (product["price"], product["regular_price"]) == (99.0, 109.0)


def test_ordinary_product_is_not_on_offer(server):
    product = server._product(_hit(name="Havregryn", isInOffer=[]))
    assert product["on_offer"] is False and product["offer"] is None and product["plus_offer"] is None


def test_offer_at_other_stores_only_does_not_count(server):
    product = server._product(
        _hit(isInOffer=[1651, 1652], cpOffer=True, cpOfferTitle="Kun andre butikker", cpOfferPrice=500, cpOfferAmount=1)
    )
    assert product["on_offer"] is False and product["offer"] is None and product["plus_offer"] is None


async def test_only_offers_adds_the_store_offer_filter(server):
    import httpx

    seen = []

    def handler(request):
        seen.append(request.read().decode())
        return httpx.Response(200, json={"hits": []})

    server._client = _index(handler)
    await server.search_products("mælk", only_offers=True)
    await server.search_products("mælk")
    assert "isInOffer:1666" in seen[0] and "isInOffer" not in seen[1]


def test_placeholder_offer_text_is_dropped_but_the_discount_stays_visible(server):
    product = server._product(
        _hit(name="Ananas i stykker", price=1795, sales_price=1500, multibuy_offer_description="Se Her", isInOffer=STORES)
    )
    assert product["on_offer"] is True and product["offer"] is None
    assert (product["price"], product["regular_price"]) == (15.0, 17.95)


def test_price_cut_has_saving_in_kroner_and_percent(server):
    product = server._product(
        _hit(name="Frilandsæg", price=4095, sales_price=2500, multibuy_offer_description="Skarp pris", isInOffer=STORES)
    )
    assert (product["saving"], product["saving_percent"]) == (15.95, 39)


def test_no_saving_without_a_price_cut(server):
    product = server._product(_hit(price=1000, sales_price=1000))
    assert (product["saving"], product["saving_percent"], product["regular_price"]) == (None, None, None)


def test_mix_offer_is_parsed_and_compared_with_buying_at_the_normal_price(server):
    product = server._product(
        _hit(name="Vådservietter", price=1200, sales_price=1200, is_multibuy=True,
             multibuy_offer_description="Mix 16 for 139,00", isInOffer=STORES)
    )
    assert product["mix_offer"] == {
        "amount": 16, "total_price": 139.0, "price_each": 8.69, "saving": 53.0, "saving_percent": 28,
    }


def test_mix_offer_without_a_saving_still_shows_the_deal(server):
    product = server._product(
        _hit(price=250, sales_price=250, is_multibuy=True, multibuy_offer_description="Mix 4 for 10,00", isInOffer=STORES)
    )
    assert product["mix_offer"]["saving"] is None and product["mix_offer"]["total_price"] == 10.0


def test_multi_item_member_offer_compares_the_total_with_buying_each(server):
    product = server._product(
        _hit(name="Ananasdrik", price=2095, sales_price=2095, isInOffer=STORES, cpOffer=True, cpOfferTitle="Scoop",
             cpOfferPrice=1800, cpOfferAmount=2, cpOriginalPrice=2095, cpPercentDiscount=57)
    )
    plus = product["plus_offer"]
    assert (plus["amount"], plus["price"], plus["saving"], plus["percent_off"]) == (2, 18.0, 23.9, 57)


def test_member_offer_percent_is_computed_when_the_shop_gives_none(server):
    product = server._product(
        _hit(price=2800, sales_price=2800, isInOffer=STORES, cpOffer=True, cpOfferPrice=2200, cpOfferAmount=1)
    )
    assert product["plus_offer"]["percent_off"] == 21


def test_products_not_on_offer_have_no_mix_offer(server):
    product = server._product(_hit(is_multibuy=True, multibuy_offer_description="Mix 4 for 10,00", isInOffer=[1651]))
    assert product["mix_offer"] is None
