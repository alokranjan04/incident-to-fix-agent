def test_total_keeps_paise(client):
    assert client.post("/orders", json={"item_id": "B200", "quantity": 1}).json()["total"] == 943.95
