"""Tests for the APScheduler integration (phase 3)."""

import os
import pytest

os.environ['PRICE_PROVIDER'] = 'mock'

from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa


# ─── Le job fonctionne en isolation ──────────────────────────────────────────

class TestJob:
    def test_job_refresh_prices_runs(self, client):
        """Le job rafraichit bien les cours des securities priceables."""
        # Seed : position + holdings
        r = _make_position(client, category='Actions', envelope='PEA', value=0, debt=0)
        pid = r.get_json()['id']
        client.put(f'/api/positions/{pid}/holdings', json={'holdings': [
            {'isin': 'FR0010315770', 'quantity': 10, 'cost_basis': 1000},
        ]}, headers=CSRF_HEADERS)

        # Avant : pas de last_price
        from models import get_db
        with get_db() as conn:
            row = conn.execute("SELECT last_price FROM securities WHERE isin='FR0010315770'").fetchone()
            assert row['last_price'] is None

        # Run manuel du job
        from services.scheduler import run_job_now
        run_job_now()

        with get_db() as conn:
            row = conn.execute("SELECT last_price, last_price_date FROM securities WHERE isin='FR0010315770'").fetchone()
            assert row['last_price'] is not None
            assert row['last_price_date'] is not None


# ─── Status endpoint ─────────────────────────────────────────────────────────

class TestStatus:
    def test_disabled_by_default(self, client):
        # Pas de SCHEDULER_ENABLED → disabled
        os.environ.pop('SCHEDULER_ENABLED', None)
        r = client.get('/api/scheduler/status')
        assert r.status_code == 200
        data = r.get_json()
        assert data['configured'] is False
        assert data['running'] is False


# ─── is_enabled helper ───────────────────────────────────────────────────────

class TestEnabledFlag:
    def test_flag_values(self):
        from services.scheduler import is_enabled
        for val in ('true', 'True', 'yes', '1'):
            os.environ['SCHEDULER_ENABLED'] = val
            assert is_enabled()
        for val in ('false', '', '0', 'no'):
            os.environ['SCHEDULER_ENABLED'] = val
            assert not is_enabled()
        os.environ.pop('SCHEDULER_ENABLED', None)
        assert not is_enabled()


# ─── init_scheduler idempotent + disabled path ──────────────────────────────

class TestInit:
    def test_init_returns_none_when_disabled(self):
        os.environ.pop('SCHEDULER_ENABLED', None)
        # Force reset (tests precedents ont pu allumer le scheduler)
        import services.scheduler as sched_mod
        sched_mod._scheduler = None
        result = sched_mod.init_scheduler()
        assert result is None

    def test_init_is_idempotent_when_enabled(self):
        import services.scheduler as sched_mod
        sched_mod._scheduler = None
        os.environ['SCHEDULER_ENABLED'] = 'true'
        os.environ['SCHEDULER_HOUR'] = '3'
        os.environ['SCHEDULER_MINUTE'] = '33'
        try:
            s1 = sched_mod.init_scheduler()
            s2 = sched_mod.init_scheduler()
            assert s1 is s2
            assert s1.running
            job = s1.get_job('refresh_prices_daily')
            assert job is not None
        finally:
            # Cleanup
            if sched_mod._scheduler and sched_mod._scheduler.running:
                sched_mod._scheduler.shutdown(wait=False)
            sched_mod._scheduler = None
            os.environ.pop('SCHEDULER_ENABLED', None)
