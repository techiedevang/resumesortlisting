"""Shared test helper: sign a test client in as the recruiter."""

USER, PASSWORD = "recruiter", "correct horse"


def sign_in(client):
    if client.post("/api/auth/setup", json={"username": USER, "password": PASSWORD}).status_code != 201:
        assert client.post("/api/auth/login", json={"username": USER, "password": PASSWORD}).status_code == 200
