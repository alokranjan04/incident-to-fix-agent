import pytest


@pytest.mark.parametrize("qty", [0, -1])
def test_quantity_below_one_is_rejected(client, qty):
    r = client.post("/orders", json={"item_id": "A100", "quantity": qty})
    assert r.status_code in (400, 422)
    assert client.get("/inventory/A100").json()["stock"] == 10
