import secrets
import logging
from uuid import UUID
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from .config import service_key
from .database import connect, query
from .retrieval import index_policy

app = FastAPI(
    title="TripLedger AI Review", docs_url=None, redoc_url=None, openapi_url=None
)


def authenticate(x_service_key: str = Header(default="")):
    if not secrets.compare_digest(x_service_key, service_key()):
        raise HTTPException(401, "Service authentication required")


class Policy(BaseModel):
    id: UUID
    content: str = Field(min_length=1, max_length=100000)
    rules: list[dict] = Field(min_length=1, max_length=100)
    # The Java service also supplies lifecycle metadata.


@app.get("/health")
def health():
    with connect() as c:
        query(c, "SELECT 1")
    return {"status": "UP"}


@app.post("/internal/index", dependencies=[Depends(authenticate)])
def index(policy: Policy):
    try:
        return index_policy(policy.model_dump(mode="json"))
    except Exception as e:
        logging.warning("policy_index_failed type=%s", type(e).__name__)
        raise HTTPException(
            502, "Policy indexing failed; check embedding settings and database"
        ) from None
