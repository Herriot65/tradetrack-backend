"""Query budgets guard against extra network round trips to the database."""
from decimal import Decimal
from time import perf_counter

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models import Trade
from core.services import get_dashboard_summary, get_win_loss_distribution
from tests.factories import AssetFactory, JournalFactory, TradeFactory


@pytest.mark.django_db
def test_summary_query_budget():
    journal = JournalFactory()
    asset = AssetFactory(journal=journal)
    Trade.objects.bulk_create([
        TradeFactory.build(journal=journal, asset=asset, pnl_r=Decimal(pnl), status=status)
        for pnl, status in [('2', None), ('-1', None), ('0.2', None), ('-0.1', 'WIN')]
    ])
    trades = Trade.objects.filter(journal=journal)
    start = perf_counter()
    with CaptureQueriesContext(connection) as queries:
        result = get_dashboard_summary(trades, Decimal('0.3'))
    print(f'Summary: {len(queries)} queries, {(perf_counter() - start) * 1000:.2f} ms')
    assert result == {
        'has_data': True, 'total_trades': 4, 'win_rate': 50.0,
        'total_r': 1.1, 'profit_factor': 1.9, 'max_drawdown_r': -1.0, 'average_r': 0.28,
    }
    assert len(queries) <= 2
    with CaptureQueriesContext(connection) as queries:
        distribution = get_win_loss_distribution(trades, Decimal('0.3'))
    assert distribution == {'has_data': True, 'wins': 2, 'losses': 1, 'break_even': 1}
    assert len(queries) == 1


@pytest.mark.django_db
def test_login_ignores_stale_session_and_reports_server_time():
    from rest_framework.test import APIClient
    from tests.factories import UserFactory
    user = UserFactory(password="synthetic-password")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer stale-token")
    response = client.post('/api/auth/login/', {
        'email': user.email, 'password': 'synthetic-password',
    }, format='json')
    assert response.status_code == 200
    assert response.data['user']['id'] == user.id
    assert response.data['access'] and response.data['refresh']
    assert float(response['Server-Timing'].split('app;dur=')[1]) >= 0
    rejected = client.post('/api/auth/login/', {
        'email': user.email, 'password': 'wrong-password',
    }, format='json')
    assert rejected.status_code == 401
