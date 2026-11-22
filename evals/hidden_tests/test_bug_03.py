def test_coupon_discount_applied(client):
    r = client.post("/orders", json={"item_id": "A100", "quantity": 1, "coupon": "SAVE10"})
    assert r.json()["total"] == 113.4
