def test_filter_by_status(client):
    order_id = client.post("/orders", json={"item_id": "A100", "quantity": 1}).json()["order_id"]
    client.post(f"/orders/{order_id}/ship")
    assert len(client.get("/orders", params={"status": "SHIPPED"}).json()) == 1
