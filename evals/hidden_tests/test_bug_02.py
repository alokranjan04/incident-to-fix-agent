def test_lowercase_coupon_works(client):
    r = client.post("/orders", json={"item_id": "A100", "quantity": 2, "coupon": "save10"})
    assert r.status_code == 201
    assert r.json()["total"] == 226.8
