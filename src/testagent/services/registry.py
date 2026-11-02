"""People, systems under test, environments and optional node modules."""

from __future__ import annotations

from testagent.services.base import Crud


class PersonService(Crud):
    table, entity, label = "person", "person", "Person"

    def delete(self, id_):  # people are deactivated, never deleted (history is kept)
        return self.update(id_, {"active": False})


class SutService(Crud):
    table, entity, label = "sut", "sut", "SUT"


class EnvironmentService(Crud):
    table, entity, label = "environment", "environment", "Environment"


class ModuleService(Crud):
    table, entity, label = "module", "module", "Group"
