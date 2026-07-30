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


@pytest.mark.asyncio
async def test_local_root_redirects_to_canonical_frontend(async_client):
    response = await async_client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/app/interactive-prototype.html"


@pytest.mark.asyncio
async def test_canonical_frontend_is_never_cached(async_client):
    response = await async_client.get("/app/interactive-prototype.html")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
