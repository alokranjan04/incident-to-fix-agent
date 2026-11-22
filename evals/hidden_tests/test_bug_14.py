def test_orders_get_unique_ids(client):
    ids = [client.post("/orders", json={"item_id": "A100", "quantity": 1}).json()["order_id"] for _ in range(3)]
    assert len(set(ids)) == 3
    assert len(client.get("/orders").json()) == 3
