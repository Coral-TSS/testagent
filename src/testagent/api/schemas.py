"""Request/response models for the M1-01 registry APIs."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from testagent.services.io_spec import DataType, IoParam

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Code = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Url = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^https?://\S+$")]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PersonIn(_In):
    name: Name
    title: str | None = None
    email: str | None = None


class PersonPatch(_In):
    name: Name | None = None
    title: str | None = None
    email: str | None = None
    active: bool | None = None


class SutIn(_In):
    code: Code
    name: Name
    description: str | None = None


class SutPatch(_In):
    name: Name | None = None
    description: str | None = None


class EnvironmentIn(_In):
    name: Name
    base_url: Url
    credential_ref: str | None = Field(default=None, max_length=200)
    start_command: str | None = Field(default=None, max_length=1000, description="starts the system under test locally")


class EnvironmentPatch(_In):
    name: Name | None = None
    base_url: Url | None = None
    credential_ref: str | None = Field(default=None, max_length=200)
    start_command: str | None = Field(default=None, max_length=1000)


class ModuleIn(_In):
    name: Name
    description: str | None = None


class ModulePatch(_In):
    name: Name | None = None
    description: str | None = None


# ---- M1-03 ontology model & API registry
Kind = Literal["entity", "action", "relation"]
EdgeRole = Literal["source", "target", "actor", "object", "ref"]
Cardinality = Literal["one_to_one", "many_to_one", "one_to_many", "many_to_many"]
Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
ApiPath = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^/\S*$", max_length=500)]


class NodeIn(_In):
    kind: Kind
    name: Name
    description: str | None = None
    module_id: UUID | None = None
    data_schema: dict[str, Any] | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    code_ref: str | None = Field(default=None, max_length=2000)
    source_node_id: UUID | None = None
    target_node_id: UUID | None = None
    inputs: list[IoParam] = Field(default_factory=list)
    outputs: list[IoParam] = Field(default_factory=list)
    input_format: str | None = Field(default=None, max_length=500)
    output_format: str | None = Field(default=None, max_length=500)
    preconditions: list[dict[str, Any]] = Field(default_factory=list)
    effects: list[dict[str, Any]] = Field(default_factory=list)


class NodePatch(_In):
    name: Name | None = None
    description: str | None = None
    module_id: UUID | None = None
    data_schema: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
    code_ref: str | None = Field(default=None, max_length=2000)
    source_node_id: UUID | None = None
    target_node_id: UUID | None = None
    inputs: list[IoParam] | None = None
    outputs: list[IoParam] | None = None
    input_format: str | None = Field(default=None, max_length=500)
    output_format: str | None = Field(default=None, max_length=500)
    preconditions: list[dict[str, Any]] | None = Field(
        default=None, description="actions: [{field: Entity.field, op, value, message}]"
    )
    effects: list[dict[str, Any]] | None = Field(
        default=None,
        description="actions: [{kind: set_field|create_object|delete_object|create_link|"
        "delete_link, field, values, node_id, link_id, when}]",
    )


class LinkIn(_In):
    from_node_id: UUID
    to_node_id: UUID
    forward_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    reverse_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    forward_api_name: str | None = Field(default=None, max_length=100)
    reverse_api_name: str | None = Field(default=None, max_length=100)
    cardinality: Cardinality = "many_to_one"
    fk_attribute_id: UUID | None = None
    via_node_id: UUID | None = None
    via_from_attribute_id: UUID | None = None
    via_to_attribute_id: UUID | None = None
    required: bool = False
    description: str | None = Field(default=None, max_length=2000)


class LinkPatch(_In):
    from_node_id: UUID | None = None
    to_node_id: UUID | None = None
    forward_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)] | None = None
    reverse_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)] | None = None
    forward_api_name: str | None = Field(default=None, max_length=100)
    reverse_api_name: str | None = Field(default=None, max_length=100)
    cardinality: Cardinality | None = None
    fk_attribute_id: UUID | None = None
    via_node_id: UUID | None = None
    via_from_attribute_id: UUID | None = None
    via_to_attribute_id: UUID | None = None
    required: bool | None = None
    description: str | None = Field(default=None, max_length=2000)


class NodeIoFromApisIn(_In):
    """Fill an action's inputs/outputs (and empty purpose/formats) from its linked APIs."""

    replace: bool = Field(default=False, description="replace instead of merging by name")


class EdgeIn(_In):
    source_node_id: UUID
    target_node_id: UUID
    role: EdgeRole


class ApiIn(_In):
    method: Method
    path: ApiPath
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    code_ref: str | None = Field(default=None, max_length=2000)
    request_schema: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    request_content_type: str | None = Field(default=None, max_length=200)
    response_content_type: str | None = Field(default=None, max_length=200)
    request_fields: list[IoParam] | None = Field(
        default=None, description="edited request table; written back into request_schema"
    )
    response_fields: list[IoParam] | None = Field(
        default=None, description="edited success-response table; written into response_schema"
    )


class ApiPatch(_In):
    method: Method | None = None
    path: ApiPath | None = None
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    code_ref: str | None = Field(default=None, max_length=2000)
    request_schema: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    request_content_type: str | None = Field(default=None, max_length=200)
    response_content_type: str | None = Field(default=None, max_length=200)
    request_fields: list[IoParam] | None = Field(
        default=None, description="edited request table; written back into request_schema"
    )
    response_fields: list[IoParam] | None = Field(
        default=None, description="edited success-response table; written into response_schema"
    )


class OpenApiImportIn(_In):
    environment_id: UUID | None = None
    url: str | None = Field(default=None, max_length=2000)


class FieldConstraint(_In):
    text: str = Field(min_length=1, max_length=2000)
    expr: str | None = Field(default=None, max_length=2000)


class FieldIn(_In):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    display_name: str | None = Field(default=None, max_length=100)
    data_type: DataType = Field(description="required: string/integer/.../enum/reference")
    unit: str | None = Field(default=None, max_length=50)
    constraints: list[FieldConstraint] = Field(default_factory=list)
    description: str | None = None
    position: int | None = None
    required: bool = False
    format: str | None = Field(default=None, max_length=200)
    example: str | None = Field(default=None, max_length=500)
    enum_values: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=100)
    ref_node_id: UUID | None = None
    storage_name: str | None = Field(
        default=None, max_length=100, description="database column when it differs from name"
    )


class FieldPatch(_In):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    display_name: str | None = Field(default=None, max_length=100)
    data_type: DataType | None = None
    unit: str | None = Field(default=None, max_length=50)
    constraints: list[FieldConstraint] | None = None
    description: str | None = None
    position: int | None = None
    required: bool | None = None
    format: str | None = Field(default=None, max_length=200)
    example: str | None = Field(default=None, max_length=500)
    enum_values: list[Annotated[str, Field(max_length=200)]] | None = Field(default=None, max_length=100)
    ref_node_id: UUID | None = None
    storage_name: str | None = Field(default=None, max_length=100)


class NodeApisIn(_In):
    api_ids: list[UUID]
