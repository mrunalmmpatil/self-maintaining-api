import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
# Explicit repository path works for CLI, API and detached workers from any cwd.
# Exported environment variables take precedence; credentials remain literal text.
load_dotenv(ROOT / ".env", override=False, interpolate=False)
SAMPLE = ROOT / "samples/bookstore"
IMAGE = "api-maintainer-python:local"
APPROVED_MODELS = frozenset(
    {
        "anthropic/claude-sonnet-5",
        "nex-agi/nex-n2.5-pro:free",
        "nvidia/nemotron-3.5-lightning:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
    }
)
# Each scenario also carries the plain-language description shown in the demo UI so users
# know which API change they are about to migrate before they start a run.
SCENARIOS = {
    "endpoint-rename": dict(
        code="S1",
        name="Endpoint rename",
        summary="The book endpoint moves to a new path. The response body is unchanged.",
        before="GET /books/{book_id}",
        after="GET /catalog/books/{book_id}",
        expect="The client should call the new path and the price quote should stay identical.",
    ),
    "response-field-rename": dict(
        code="S2",
        name="Response field rename",
        summary="The book title is returned under a new field name.",
        before="Book.title",
        after="Book.name",
        expect="The client should read the new field while the displayed title stays the same.",
    ),
    "nested-price": dict(
        code="S3",
        name="Nested price / cents conversion",
        summary="Price moves into a nested object and changes unit from dollars to integer cents.",
        before="Book.price — 20.0 (US dollars)",
        after="Book.pricing.amount_cents — 2000 (US cents)",
        expect="The client should divide by 100, so 2000 cents still displays as 20.00 and two copies total 40.00.",
    ),
    "wrapper-price": dict(
        code="S4",
        name="Wrapped price / unrelated field",
        summary="The same cents conversion as S3, but the price is read through a wrapper function and an "
        "unrelated membership price uses the same field name.",
        before="Book.price — 20.0 (US dollars)",
        after="Book.pricing.amount_cents — 2000 (US cents)",
        expect="Only the API-derived price should change; the unrelated membership price of 5.00 must be left alone.",
    ),
    "optional-field": dict(
        code="S5",
        name="Optional field addition",
        summary="The response gains an optional subtitle. Nothing the client already uses changes.",
        before="Book { id, title, price }",
        after="Book { id, title, price, subtitle? }",
        expect="No client change is needed, so the expected result is an empty patch and a no-change outcome.",
    ),
    "required-input": dict(
        code="S6",
        name="Missing required country",
        summary="The endpoint now requires a customer country, and the client has no country value or source.",
        before="GET /books/{book_id}",
        after="GET /books/{book_id}?country=… (required)",
        expect="No country can be invented, so the expected result is documented manual work for the caller change.",
    ),
    "mixed": dict(
        code="S7",
        name="Endpoint rename and missing country",
        summary="Two changes at once: the endpoint moves and a customer country becomes required.",
        before="GET /books/{book_id}",
        after="GET /catalog/books/{book_id}?country=… (required)",
        expect="The path repair should be applied and kept while the missing country is documented as remaining "
        "manual work, leaving verification incomplete.",
    ),
}


def data_root():
    return Path(os.environ.get("API_MAINTAINER_DATA", ROOT / ".local-data")).resolve()
