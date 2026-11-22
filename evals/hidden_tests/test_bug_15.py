def test_cost_price_not_exposed(client):
    assert "cost_price" not in client.get("/inventory/A100").json()
