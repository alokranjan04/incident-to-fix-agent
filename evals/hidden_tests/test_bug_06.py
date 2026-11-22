def test_can_buy_last_item(client):
    assert client.post("/orders", json={"item_id": "C300", "quantity": 1}).status_code == 201
