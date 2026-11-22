def test_total_is_for_all_units(client):
    assert client.post("/orders", json={"item_id": "A100", "quantity": 2}).json()["total"] == 252.0
