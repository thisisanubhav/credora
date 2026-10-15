"""API Gateway HTTP API v2 adapter; authentication is enforced by the route layer."""

from mangum import Mangum

from apps.api.main import app

handler = Mangum(app, lifespan="off")
