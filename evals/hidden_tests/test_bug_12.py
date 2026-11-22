def test_low_stock_threshold(client):
    ids = sorted(p["item_id"] for p in client.get("/inventory/low-stock", params={"threshold": 5}).json())
    assert ids == ["B200", "C300"]
