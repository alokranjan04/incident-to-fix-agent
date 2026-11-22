def test_shipped_order_cannot_be_cancelled(client):
    order_id = client.post("/orders", json={"item_id": "A100", "quantity": 1}).json()["order_id"]
    client.post(f"/orders/{order_id}/ship")
    assert client.post(f"/orders/{order_id}/cancel").status_code == 409
