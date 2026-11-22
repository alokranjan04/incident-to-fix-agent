def test_unknown_order_is_404(client):
    assert client.get("/orders/999").status_code == 404
