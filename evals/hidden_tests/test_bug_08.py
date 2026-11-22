def test_cancel_returns_stock(client):
    order_id = client.post("/orders", json={"item_id": "C300", "quantity": 1}).json()["order_id"]
    client.post(f"/orders/{order_id}/cancel")
    assert client.get("/inventory/C300").json()["stock"] == 1
