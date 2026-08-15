from __future__ import annotations

from django.db.models import Q
from django.test import SimpleTestCase

from control.services.tenant_provisioning_publication_readers import (
    DjangoGroupDBConfigReadOnlyCatalog,
)


class _FakeQuerySet:
    def __init__(self, ledger, *, exists_result=False, fail_exists=False):
        self.ledger = ledger
        self.exists_result = exists_result
        self.fail_exists = fail_exists

    def filter(self, *args, **kwargs):
        self.ledger.append(("filter", args, kwargs))
        return self

    def exclude(self, *args, **kwargs):
        self.ledger.append(("exclude", args, kwargs))
        return self

    def exists(self):
        self.ledger.append(("exists", (), {}))
        if self.fail_exists:
            raise RuntimeError("central provider detail must remain private")
        return self.exists_result


class _FakeManager:
    def __init__(self, queryset, ledger):
        self.queryset = queryset
        self.ledger = ledger

    def using(self, alias):
        self.ledger.append(("using", (alias,), {}))
        return self.queryset

    def create(self, *args, **kwargs):  # pragma: no cover - safety tripwire
        raise AssertionError("read-only catalog must never create")

    def update(self, *args, **kwargs):  # pragma: no cover - safety tripwire
        raise AssertionError("read-only catalog must never update")

    def delete(self, *args, **kwargs):  # pragma: no cover - safety tripwire
        raise AssertionError("read-only catalog must never delete")


def _fake_model(*, exists_result=False, fail_exists=False):
    ledger = []
    queryset = _FakeQuerySet(
        ledger,
        exists_result=exists_result,
        fail_exists=fail_exists,
    )
    manager = _FakeManager(queryset, ledger)
    return type("FakeGroupDBConfig", (), {"objects": manager}), ledger


class DjangoGroupDBConfigReadOnlyCatalogTests(SimpleTestCase):
    def test_requires_explicit_central_database_alias(self):
        model, _ = _fake_model()

        with self.assertRaisesRegex(ValueError, "central_database_alias_required"):
            DjangoGroupDBConfigReadOnlyCatalog(using="", model=model)

    def test_group_config_check_is_exists_only_on_explicit_alias(self):
        model, ledger = _fake_model(exists_result=True)
        catalog = DjangoGroupDBConfigReadOnlyCatalog(
            using="control-central",
            model=model,
        )

        self.assertTrue(catalog.read_only)
        self.assertTrue(catalog.group_config_exists(group_id="group-1"))
        self.assertEqual(
            ledger,
            [
                ("using", ("control-central",), {}),
                ("filter", (), {"group_id": "group-1"}),
                ("exists", (), {}),
            ],
        )

    def test_identifier_conflict_matches_contract_and_excludes_same_group(self):
        model, ledger = _fake_model(exists_result=True)
        catalog = DjangoGroupDBConfigReadOnlyCatalog(using="default", model=model)

        self.assertTrue(
            catalog.identifier_conflict_exists(
                group_id="group-1",
                db_alias="city_db",
                db_name="city_db",
                db_user="city_app",
            )
        )

        self.assertEqual(ledger[0], ("using", ("default",), {}))
        self.assertEqual(
            ledger[1],
            (
                "filter",
                (
                    Q(db_alias="city_db")
                    | Q(db_name="city_db")
                    | Q(db_user="city_app"),
                ),
                {},
            ),
        )
        self.assertEqual(ledger[2], ("exclude", (), {"group_id": "group-1"}))
        self.assertEqual(ledger[3], ("exists", (), {}))

    def test_ambiguous_read_failure_propagates_fail_closed(self):
        model, _ = _fake_model(fail_exists=True)
        catalog = DjangoGroupDBConfigReadOnlyCatalog(using="default", model=model)

        with self.assertRaisesRegex(RuntimeError, "central provider detail"):
            catalog.group_config_exists(group_id="group-1")


