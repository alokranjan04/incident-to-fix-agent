def test_list_includes_first_order(client):
    for _ in range(2):
        client.post("/orders", json={"item_id": "A100", "quantity": 1})
    assert len(client.get("/orders").json()) == 2
