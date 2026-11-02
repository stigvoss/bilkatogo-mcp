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


CART_WITH_OBJECTID = {
    "lines": [
        {
            "lines": [
                {
                    "orderlines": [
                        {"product": {"objectID": 85465, "name": "Havregryn"}, "quantity": 2, "unitprice": 795, "amount": 1590},
                        {"product": {"objectID": 111, "name": "Mælk"}, "quantity": 1, "unitprice": 1000, "amount": 1000},
                        {"product": {"objectID": 222, "name": "Smør"}, "quantity": 1, "unitprice": 2000, "amount": 2000},
                    ]
                }
            ]
        }
    ],
    "stat": {"price": 4590},
}


async def test_cart_reads_the_id_from_objectid(server, monkeypatch):
    import httpx

    async def fake_shop(path, params=None):
        return CART_WITH_OBJECTID

    monkeypatch.setattr(server, "_shop", fake_shop)
    server._client = _index(lambda request: httpx.Response(200, json={"results": [None, None, None]}))
    cart = await server.get_cart()
    assert [line["product_id"] for line in cart["lines"]] == [85465, 111, 222]
    assert all(pid is not None for pid in [line["product_id"] for line in cart["lines"]])


async def test_add_to_cart_adds_to_an_existing_line_found_by_objectid(server, monkeypatch):
    seen = {}

    async def fake_shop(path, params=None):
        if path == "v6/Cart":
            return CART_WITH_OBJECTID
        seen["params"] = params
        return {"productId": params["productId"], "productAmount": params["count"], "unitCount": 1, "sum": 100}

    monkeypatch.setattr(server, "_shop", fake_shop)
    result = await server.add_to_cart(85465, 1)
    assert result["quantity"] == 3  # 2 already in the cart + 1


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


# Real index hits for store 1666, trimmed to what matters. Prices are in øre.
HERE = [1666]


def _lookup(server, results):
    """Serve `results` as the index's answer and remember what was asked."""
    import httpx

    server.asked = []

    def handler(request):
        server.asked.append(request.read().decode())
        return httpx.Response(200, json={"results": results})

    server._client = _index(handler)


def _in_store(**fields):
    return _hit(inStockStore=HERE, isInAssortmentIn=HERE, **fields)


async def test_get_products_finds_known_ids_and_flags_the_unknown_one(server):
    _lookup(server, [_in_store(id=85465, name="Havregryn", brand="Salling", netcontent="1 kg"), None,
                     _in_store(id=3, name="Ananas")])
    result = await server.get_products(["85465", "999999999", "3"])
    assert [p["product_id"] for p in result] == [85465, 999999999, 3]  # one id type everywhere
    assert result[1] == {"product_id": 999999999, "found": False}
    assert (result[0]["name"], result[0]["brand"], result[0]["size"]) == ("Havregryn", "Salling", "1 kg")
    assert result[0]["found"] is True and result[0]["offer"] is None


async def test_price_cut_shows_the_reduced_price_and_nothing_is_required(server):
    _lookup(server, [_in_store(id=40258, name="Frilandsæg", price=4095, sales_price=2500,
                               multibuy_offer_description="Skarp pris", isInOffer=HERE,
                               unitOfMeasurePrice=410, unitOfMeasurePriceUnits="Stk.",
                               storeData={"1666": {"unitsOfMeasurePrice": 410, "unitsOfMeasureShowPrice": 250,
                                                   "unitsOfMeasurePriceUnit": "Stk."}})])
    egg = (await server.get_products(["40258"]))[0]
    assert (egg["price"], egg["regular_price"], egg["saving"], egg["saving_percent"]) == (25.0, 40.95, 15.95, 39)
    assert egg["offer"] == {"label": "Skarp pris", "price": 25.0, "requires": None, "valid_to": None}
    # Per piece at the current price (25.00 / 10), not at the regular price (40.95 / 10 = 4.10).
    assert (egg["unit_price_per_kg_or_l"], egg["unit"]) == (2.5, "Stk.")


async def test_member_offer_price_is_the_offer_price_with_its_end_date(server):
    # A real yoghurt: 20.00 list, 15.00 shelf price, 10.00 for members until 13 November.
    _lookup(server, [_in_store(id=19789, price=2000, sales_price=1500, isInOffer=HERE, cpOffer=True,
                               cpOfferTitle="Yoggi yoghurt", cpOfferPrice=1000, cpOfferAmount=1,
                               cpPercentDiscount=50, cpOfferFromDate="2026-10-30", cpOfferToDate="2026-11-13")])
    yoghurt = (await server.get_products(["19789"]))[0]
    assert yoghurt["price"] == 15.0  # what anyone pays; the member price is conditional
    assert yoghurt["offer"] == {"label": "Yoggi yoghurt", "price": 10.0, "requires": "member", "valid_to": "2026-11-13"}
    assert yoghurt["plus_offer"]["saving"] == 10.0


async def test_multi_item_member_offer_gives_the_price_per_item(server):
    _lookup(server, [_in_store(id=1, price=2095, sales_price=2095, isInOffer=HERE, cpOffer=True, cpOfferTitle="Scoop",
                               cpOfferPrice=1800, cpOfferAmount=2, cpOriginalPrice=2095, cpOfferToDate="2026-10-30")])
    offer = (await server.get_products(["1"]))[0]["offer"]
    assert (offer["price"], offer["requires"], offer["valid_to"]) == (9.0, "member, buy 2", "2026-10-30")


async def test_mix_offer_gives_the_price_each_and_the_amount_to_buy(server):
    _lookup(server, [_in_store(id=18381, name="Bananer", price=275, sales_price=275, is_multibuy=True,
                               multibuy_offer_description="Mix 10 for 25,00", isInOffer=HERE)])
    bananas = (await server.get_products(["18381"]))[0]
    assert bananas["price"] == 2.75
    assert bananas["offer"] == {"label": "Mix 10 for 25,00", "price": 2.5, "requires": "buy 10", "valid_to": None}


async def test_stock_and_range_are_for_this_store(server):
    # A real beer that the store sells but does not have in stock, and a product outside its range.
    _lookup(server, [_hit(id=39599, isInStock=1, inStockStore=[1651], isInAssortmentIn=HERE),
                     _hit(id=70105, isInStock=1, inStockStore=HERE, isInAssortmentIn=[1651])])
    unstocked, not_sold = await server.get_products([39599, 70105])
    assert (unstocked["in_stock"], unstocked["sold_here"]) == (False, True)
    # Shelves may hold it, but a product the store does not sell cannot be had.
    assert (not_sold["in_stock"], not_sold["sold_here"]) == (False, False)


def test_stock_falls_back_to_the_global_flag_when_the_store_list_is_missing(server):
    assert server._product(_hit(isInStock=1))["in_stock"] is True
    assert server._product(_hit(isInStock=0))["in_stock"] is False
    assert server._product(_hit(isInStock=1, inStockStore=[1651]))["in_stock"] is False


async def test_more_than_fifty_ids_is_refused_not_silently_cut(server):
    _lookup(server, [])
    with pytest.raises(ToolError, match="at most 50"):
        await server.get_products([str(i) for i in range(51)])
    assert not server.asked


async def test_fifty_ids_are_accepted(server):
    _lookup(server, [None] * 50)
    assert len(await server.get_products([str(i) for i in range(50)])) == 50


async def test_numbers_are_accepted_as_ids_even_through_the_tool_schema(server):
    _lookup(server, [_in_store(id=85465, name="Havregryn")])
    await server.mcp.call_tool("get_products", {"product_ids": [85465]})  # schema validation, not just the function
    assert '"objectID":"85465"' in server.asked[0].replace(" ", "")


async def test_an_unreachable_index_gives_a_short_message_not_a_crash(server):
    import httpx

    server._client = _index(lambda request: httpx.Response(503))
    with pytest.raises(ToolError, match="try again"):
        await server.get_products(["1"])


async def test_get_products_with_no_ids_skips_the_request(server):
    _lookup(server, [])
    assert await server.get_products([]) == []
    assert not server.asked


async def test_cart_with_objectid_only_products_gets_brand_and_size(cart_server):
    """The real cart has no `id` on its products, only objectID; details must still be found."""
    import httpx

    cart_server_data = {
        "lines": [{"lines": [{"orderlines": [
            {"product": {"objectID": 85465, "name": "Finvalsede havregryn"}, "quantity": 2, "unitprice": 795, "amount": 1590},
        ]}]}],
        "stat": {"price": 1590},
    }

    async def fake_shop(path, params=None):
        return cart_server_data

    cart_server._shop = fake_shop
    cart_server._client = _index(
        lambda request: httpx.Response(200, json={"results": [{"brand": "Salling", "netcontent": "1 kg"}]})
    )
    line = (await cart_server.get_cart())["lines"][0]
    assert (line["product_id"], line["brand"], line["size"]) == (85465, "Salling", "1 kg")


# ---- findings from the live test report --------------------------------------------------------
def test_unit_price_follows_the_current_price_of_this_store(server):
    eggs = server._product(_hit(price=4095, sales_price=2500, unitOfMeasurePrice=410, unitOfMeasurePriceUnits="Stk.",
                                storeData={"1666": {"unitsOfMeasurePrice": 410, "unitsOfMeasureShowPrice": 250,
                                                    "unitsOfMeasurePriceUnit": "Stk."},
                                           "1651": {"unitsOfMeasureShowPrice": 999}}))
    assert (eggs["unit_price"], eggs["unit"]) == (2.5, "Stk.")  # not 4.10, and not another store's


def test_unit_price_falls_back_to_the_top_level_field_without_store_data(server):
    oats = server._product(_hit(unitOfMeasurePrice=795, unitOfMeasurePriceUnits="Kg."))
    assert (oats["unit_price"], oats["unit"]) == (7.95, "Kg.")


async def test_cart_price_per_unit_uses_the_store_price_and_asks_only_for_this_store(cart_server):
    import httpx

    asked = {}

    def handler(request):
        asked["body"] = request.read().decode()
        hit = {"brand": "Salling", "netcontent": "10 stk", "unitOfMeasurePrice": 410,
               "storeData": {"1666": {"unitsOfMeasureShowPrice": 250, "unitsOfMeasurePriceUnit": "Stk."}}}
        return httpx.Response(200, json={"results": [None, hit]})

    cart_server._client = _index(handler)
    line = (await cart_server.get_cart())["lines"][0]
    assert (line["price_per_unit"], line["unit"]) == (2.5, "Stk.")
    assert "storeData.1666" in asked["body"]


def test_an_empty_brand_is_null_everywhere(server):
    assert server._product(_hit(brand=""))["brand"] is None


async def test_changing_the_cart_reports_the_line_total_and_a_real_unit_price(server, monkeypatch):
    async def fake_shop(path, params=None):
        # The shop's productUnitPrice is the price of the whole line (3 x 7.95), and its id is a string.
        return {"productId": "85465", "productAmount": 3, "productUnitPrice": 2385, "unitCount": 3, "sum": 5000}

    monkeypatch.setattr(server, "_shop", fake_shop)
    result = await server.set_cart_quantity(85465, 3)
    assert result["product_id"] == 85465  # a number, as in every other tool
    assert (result["quantity"], result["line_total"], result["unit_price"]) == (3, 23.85, 7.95)


async def test_removing_a_line_has_no_unit_price(server, monkeypatch):
    async def fake_shop(path, params=None):
        return {"productId": "85465", "productAmount": 0, "productUnitPrice": 0, "unitCount": 0, "sum": 0}

    monkeypatch.setattr(server, "_shop", fake_shop)
    result = await server.set_cart_quantity(85465, 0)
    assert (result["quantity"], result["line_total"], result["unit_price"]) == (0, 0.0, None)


async def test_cart_lines_say_which_are_services(cart_server):
    """The packing fee is a line in the cart (group "Services", category "Services")."""
    def product(object_id, name, lvl0):
        return {"objectID": object_id, "name": name, "categories": {"lvl0": [lvl0]}}

    def entry(headline, *products):
        return {"headline": headline, "lines": [{"orderlines": [
            {"product": p, "quantity": 1, "unitprice": 1000, "amount": 1000} for p in products]}]}

    async def fake_shop(path, params=None):
        return {"lines": [
            entry("Services", product(81474, "Pakkeservice", "Services")),
            entry("Mejeri & køl", product(85465, "Havregryn", "Kolonial")),
            entry("Services", {"objectID": 7, "name": "Kun sektion"}),  # only the section says service
            entry("Andet", product(8, "Kun kategori", "Emballage")),  # only the category says service
        ], "stat": {}}

    cart_server._shop = fake_shop
    cart_server._client = _index(lambda request: __import__("httpx").Response(200, json={"results": []}))
    flags = {line["name"]: line["is_service"] for line in (await cart_server.get_cart())["lines"]}
    assert flags == {"Pakkeservice": True, "Havregryn": False, "Kun sektion": True, "Kun kategori": True}


def test_descriptions_do_not_overclaim_the_order_counts(server):
    import asyncio

    tools = {t.name: t.description for t in asyncio.run(server.mcp.list_tools())}
    assert "originally placed" not in tools["get_order"]  # older orders do not keep the undelivered lines
    assert "as ordered" in tools["list_orders"] and "delivered and invoiced" in tools["list_orders"]
    assert "is_service" in tools["get_cart"]
