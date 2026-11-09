"""Local backend latency benchmark; run explicitly with pytest -s tests/benchmark_history.py."""
import json
import math
from pathlib import Path
from statistics import median
from time import perf_counter

import pytest
from rest_framework.test import APIClient
from core.models import Trade
from tests.factories import AssetFactory, JournalFactory, TradeFactory


@pytest.mark.django_db
def test_history_latency():
    journal = JournalFactory()
    asset = AssetFactory(journal=journal)
    Trade.objects.bulk_create(TradeFactory.build_batch(
        126, journal=journal, asset=asset, notes="Synthetic journal note. " * 100,
    ))
    client = APIClient()
    client.force_authenticate(user=journal.user)
    url = f"/api/journals/{journal.id}/trades/"
    def load(compact):
        responses = []
        page = 1
        while True:
            response = client.get(url, {"page_size": 1000 if compact else 200,
                                       "compact": "1" if compact else "0",
                                       "ordering": "entry_datetime,id", "page": page})
            assert response.status_code == 200
            responses.append(response)
            if not response.data["next"]:
                break
            page += 1
        return responses
    for compact in [False, True]:
        load(compact)  # Warm URL resolution, serializer imports and DB connection.
    measurements = {False: [], True: []}
    results = {}
    for _ in range(20):
        for compact in [False, True]:
            start = perf_counter()
            responses = load(compact)
            measurements[compact].append((perf_counter() - start) * 1000)
            results[compact] = {"requests": len(responses), "response_bytes": sum(len(r.content) for r in responses)}
    report = {"environment": "Local Django APIClient, SQLite test database; excludes network/TLS", "synthetic_trades": 126,
              "results": {"compact" if compact else "full": {**results[compact], "samples": len(times),
                  "median_ms": round(median(times), 1), "p95_ms": round(sorted(times)[math.ceil(len(times) * .95) - 1], 1)}
                  for compact, times in measurements.items()}}
    destination = Path('/workspace/tradetrack-frontend/artifacts/latency/backend-latency.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
