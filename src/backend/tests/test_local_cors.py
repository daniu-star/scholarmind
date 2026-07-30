"""Local browser origins can call the development API on port 8000."""

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5500",
        "http://localhost:8080",
    ],
)
async def test_local_dev_server_preflight_is_allowed(async_client, origin):
    response = await async_client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
