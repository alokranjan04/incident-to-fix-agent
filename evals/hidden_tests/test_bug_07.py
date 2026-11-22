def test_stock_goes_down(client):
    assert client.post("/orders", json={"item_id": "C300", "quantity": 1}).status_code == 201
    assert client.post("/orders", json={"item_id": "C300", "quantity": 1}).status_code == 409
    assert client.get("/inventory/C300").json()["stock"] == 0
