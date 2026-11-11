from uuid import uuid4

from catalog.seed_data import product_id


async def _names(client, **params) -> list[str]:
    response = await client.get("/products", params=params)
    assert response.status_code == 200
    return [item["name"] for item in response.json()["items"]]


async def test_list_default_pagination(client) -> None:
    body = (await client.get("/products")).json()
    assert body["total"] == 24
    assert body["page"] == 1
    assert body["page_size"] == 12
    assert len(body["items"]) == 12


async def test_list_second_page_and_last_page(client) -> None:
    first = (await client.get("/products", params={"page_size": 10})).json()
    third = (await client.get("/products", params={"page_size": 10, "page": 3})).json()
    assert len(first["items"]) == 10
    assert len(third["items"]) == 4
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in third["items"]}


async def test_page_beyond_end_is_empty(client) -> None:
    body = (await client.get("/products", params={"page": 99})).json()
    assert body["items"] == []
    assert body["total"] == 24


async def test_page_size_max_is_48(client) -> None:
    ok = await client.get("/products", params={"page_size": 48})
    assert ok.status_code == 200
    assert len(ok.json()["items"]) == 24
    too_big = await client.get("/products", params={"page_size": 49})
    assert too_big.status_code == 422
    assert isinstance(too_big.json()["detail"], str)


async def test_invalid_page_params_return_422_with_detail(client) -> None:
    for params in ({"page": 0}, {"page_size": 0}, {"page": "abc"}, {"sort": "random"}):
        response = await client.get("/products", params=params)
        assert response.status_code == 422, params
        assert "detail" in response.json()


async def test_inverted_price_range_is_422(client) -> None:
    response = await client.get(
        "/products", params={"min_price_cents": 5000, "max_price_cents": 1000}
    )
    assert response.status_code == 422


async def test_search_ignores_accents_and_case(client) -> None:
    for term in ("luminaria", "LUMINARIA", "Luminária", "luminária"):
        assert "Luminária Arco Dourado" in await _names(client, q=term)


async def test_search_accented_term_matches_unaccented_stored_text(client) -> None:
    assert "Tênis de Corrida Vento" in await _names(client, q="tenis")
    assert "Cafeteira Prensa Francesa" in await _names(client, q="cafe")


async def test_search_multiple_words_requires_all(client) -> None:
    names = await _names(client, q="fone bluetooth")
    assert names[0] == "Fone Bluetooth Nova ANC"
    assert "Relógio GPS Trail" not in names


async def test_search_matches_description_and_tags(client) -> None:
    assert "Garrafa Térmica Aço 750 ml" in await _names(client, q="gelada")
    assert "Kit de Elásticos de Força" in await _names(client, q="musculacao")


async def test_search_ranks_name_before_description(client) -> None:
    names = await _names(client, q="relogio")
    assert set(names[:2]) == {"Relógio de Parede Minimal", "Relógio GPS Trail"}


async def test_search_tolerates_small_typo(client) -> None:
    assert "Luminária Arco Dourado" in await _names(client, q="luminara")


async def test_search_with_no_match_returns_empty(client) -> None:
    body = (await client.get("/products", params={"q": "xyzqwk"})).json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_search_treats_wildcards_literally(client) -> None:
    assert await _names(client, q="%") == ["Teclado Mecânico Forge 75%"]
    assert await _names(client, q="_") == []


async def test_filter_by_category(client) -> None:
    body = (await client.get("/products", params={"category": "esporte", "page_size": 48})).json()
    assert body["total"] == 8
    assert {item["category"] for item in body["items"]} == {"esporte"}


async def test_filter_by_price_range(client) -> None:
    body = (
        await client.get(
            "/products",
            params={"min_price_cents": 10000, "max_price_cents": 20000, "page_size": 48},
        )
    ).json()
    prices = [item["price_cents"] for item in body["items"]]
    assert prices
    assert all(10000 <= price <= 20000 for price in prices)


async def test_filters_combine(client) -> None:
    names = await _names(client, category="casa", max_price_cents=10000, q="decoracao")
    assert set(names) <= {
        "Vaso de Cerâmica Terra",
        "Relógio de Parede Minimal",
        "Organizador de Bambu Set",
    }
    assert names


async def test_sort_price_asc_and_desc(client) -> None:
    asc = (await client.get("/products", params={"sort": "price_asc", "page_size": 48})).json()
    desc = (await client.get("/products", params={"sort": "price_desc", "page_size": 48})).json()
    asc_prices = [i["price_cents"] for i in asc["items"]]
    assert asc_prices == sorted(asc_prices)
    assert asc_prices[0] == 4990
    assert [i["price_cents"] for i in desc["items"]] == sorted(asc_prices, reverse=True)
    assert desc["items"][0]["price_cents"] == 64990


async def test_sort_rating(client) -> None:
    items = (await client.get("/products", params={"sort": "rating", "page_size": 48})).json()[
        "items"
    ]
    ratings = [i["rating"] for i in items]
    assert ratings == sorted(ratings, reverse=True)
    assert ratings[0] == 4.9


async def test_sort_newest(client) -> None:
    items = (await client.get("/products", params={"sort": "newest", "page_size": 48})).json()[
        "items"
    ]
    dates = [i["created_at"] for i in items]
    assert dates == sorted(dates, reverse=True)
    assert items[0]["slug"] == "kit-elasticos-forca"


async def test_sort_relevance_without_query_uses_popularity(client) -> None:
    items = (await client.get("/products", params={"page_size": 48})).json()["items"]
    reviews = [i["reviews_count"] for i in items]
    assert reviews == sorted(reviews, reverse=True)


async def test_get_product_by_id_has_contract_shape(client) -> None:
    response = await client.get(f"/products/{product_id('smartwatch-orbit')}")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "slug",
        "name",
        "description",
        "price_cents",
        "currency",
        "category",
        "image_url",
        "rating",
        "reviews_count",
        "tags",
        "merchant",
        "created_at",
    }
    assert body["price_cents"] == 49990
    assert body["currency"] == "BRL"
    assert body["merchant"]["slug"] == "aurora-tech"
    assert set(body["merchant"]) == {"id", "slug", "name"}


async def test_get_product_unknown_id_is_404(client) -> None:
    response = await client.get(f"/products/{uuid4()}")
    assert response.status_code == 404
    assert "detail" in response.json()


async def test_get_product_malformed_id_is_422(client) -> None:
    response = await client.get("/products/not-a-uuid")
    assert response.status_code == 422
    assert "detail" in response.json()


async def test_get_product_by_slug(client) -> None:
    response = await client.get("/products/slug/mouse-glide-pro")
    assert response.status_code == 200
    assert response.json()["id"] == str(product_id("mouse-glide-pro"))


async def test_get_product_unknown_slug_is_404(client) -> None:
    response = await client.get("/products/slug/nao-existe")
    assert response.status_code == 404
    assert response.json() == {"detail": "product not found"}


async def test_by_ids_skips_unknown_and_keeps_order(client) -> None:
    a, b = product_id("corda-pular-speed"), product_id("vaso-ceramica-terra")
    response = await client.get("/products/by-ids", params={"ids": f"{b},{uuid4()},{a}"})
    assert response.status_code == 200
    body = response.json()
    assert [i["id"] for i in body["items"]] == [str(b), str(a)]
    assert body["total"] == 2


async def test_by_ids_all_unknown_is_empty(client) -> None:
    body = (await client.get("/products/by-ids", params={"ids": str(uuid4())})).json()
    assert body["items"] == []


async def test_by_ids_invalid_or_missing_is_422(client) -> None:
    assert (await client.get("/products/by-ids", params={"ids": "abc"})).status_code == 422
    assert (await client.get("/products/by-ids")).status_code == 422


async def test_by_ids_does_not_collide_with_id_route(client) -> None:
    response = await client.get(
        "/products/by-ids", params={"ids": str(product_id("kit-elasticos-forca"))}
    )
    assert response.status_code == 200


async def test_categories_with_counts(client) -> None:
    response = await client.get("/categories")
    assert response.status_code == 200
    by_slug = {c["slug"]: c for c in response.json()}
    assert by_slug["tecnologia"] == {"slug": "tecnologia", "label": "Tecnologia", "count": 8}
    assert by_slug["casa"]["label"] == "Casa e decoração"
    assert by_slug["esporte"]["label"] == "Esporte e aventura"
    assert sum(c["count"] for c in by_slug.values()) == 24


async def test_etag_and_cache_control_on_reads(client) -> None:
    for path in ("/products", "/categories", "/products/slug/mouse-glide-pro"):
        response = await client.get(path)
        assert response.headers["etag"].startswith('"')
        assert response.headers["cache-control"] == "public, max-age=60"


async def test_if_none_match_returns_304(client) -> None:
    first = await client.get("/products", params={"q": "fone"})
    etag = first.headers["etag"]
    second = await client.get("/products", params={"q": "fone"}, headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["etag"] == etag
    assert second.headers["cache-control"] == "public, max-age=60"


async def test_weak_etag_and_list_are_accepted(client) -> None:
    etag = (await client.get("/categories")).headers["etag"]
    response = await client.get("/categories", headers={"If-None-Match": f'"other", W/{etag}'})
    assert response.status_code == 304


async def test_stale_etag_returns_full_body(client) -> None:
    response = await client.get("/categories", headers={"If-None-Match": '"stale"'})
    assert response.status_code == 200
    assert response.json()


async def test_etag_differs_between_queries(client) -> None:
    a = await client.get("/products", params={"category": "casa"})
    b = await client.get("/products", params={"category": "esporte"})
    assert a.headers["etag"] != b.headers["etag"]


async def test_errors_are_not_cached(client) -> None:
    response = await client.get(f"/products/{uuid4()}")
    assert "etag" not in response.headers


async def test_health_and_ready(client) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    ready = await client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"ready": True}
