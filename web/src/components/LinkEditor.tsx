import { ListTable } from "./ListView";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, Modal, Select, Space, Switch, Tag, Typography } from "antd";
import { useEffect } from "react";

import { ApiError, api, describeError } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Cardinality, EntityField, Link, ModelNode } from "../api/types";
import { CARD_LABEL, CARD_SHORT, forwardText, reverseText } from "./links";

type Values = {
  from_node_id?: string;
  to_node_id?: string;
  forward_name?: string;
  reverse_name?: string;
  forward_api_name?: string;
  reverse_api_name?: string;
  cardinality: Cardinality;
  fk_attribute_id?: string | null;
  via_node_id?: string | null;
  via_from_attribute_id?: string | null;
  via_to_attribute_id?: string | null;
  required?: boolean;
  description?: string;
};

const API_NAME = /^[a-z][A-Za-z0-9_]{0,99}$/;

/** Create / edit one relation (link type): both readings, cardinality, foreign key or junction. */
export function LinkEditor({
  sutId,
  open,
  link,
  defaults,
  entities,
  fields,
  onClose,
}: {
  sutId: string;
  open: boolean;
  link?: Link | null;
  defaults?: Partial<Values>;
  entities: ModelNode[];
  fields: EntityField[];
  onClose: () => void;
}) {
  const [form] = Form.useForm<Values>();
  const qc = useQueryClient();
  const { modal, message } = App.useApp();
  useEffect(() => {
    if (!open) return;
    form.resetFields();
    form.setFieldsValue(
      link
        ? {
            ...link,
            forward_api_name: link.forward_api_name || undefined,
            reverse_api_name: link.reverse_api_name || undefined,
            description: link.description || undefined,
          }
        : { cardinality: "many_to_one", required: false, ...defaults },
    );
  }, [open, link, defaults, form]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["links", sutId] });
    qc.invalidateQueries({ queryKey: ["graph", sutId] });
    qc.invalidateQueries({ queryKey: ["node"] });
  };
  const save = useApiMutation(
    (body: Values) =>
      link
        ? api<Link>(`/links/${link.id}`, { method: "PATCH", body })
        : api<Link>(`/suts/${sutId}/links`, { method: "POST", body }),
    {
      success: link ? "Link saved" : "Link created",
      onSuccess: () => {
        refresh();
        onClose();
      },
    },
  );
  const remove = async (confirm: boolean) => {
    if (!link) return;
    try {
      await api(`/links/${link.id}`, { method: "DELETE", params: { confirm } });
      message.success("Link deleted (traceable in the change log)");
      refresh();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === "CONFLICT" && !confirm) {
        modal.confirm({
          title: "Link still referenced",
          content: (
            <>
              <p>{err.message}</p>
              <ul>
                {err.related.map((r) => (
                  <li key={r}>{r.split(":").slice(2).join(":") || r}</li>
                ))}
              </ul>
            </>
          ),
          okText: "Delete anyway",
          okButtonProps: { danger: true },
          onOk: () => remove(true),
        });
      } else message.error(describeError(err));
    }
  };

  const v = Form.useWatch([], form) as Values | undefined;
  const name = (id?: string | null) => entities.find((e) => e.id === id)?.name || "?";
  const entityOptions = entities.filter((e) => e.kind === "entity").map((e) => ({ value: e.id, label: e.name }));
  const fieldsOf = (ids: (string | undefined | null)[]) =>
    fields
      .filter((f) => ids.includes(f.node_id))
      .map((f) => ({
        value: f.id,
        label: `${f.node_name}.${f.name}${f.data_type === "reference" && f.ref_node_name ? ` → ${f.ref_node_name}` : ""}`,
      }));
  const card = v?.cardinality || "many_to_one";
  const fkOwners =
    card === "many_to_one" ? [v?.from_node_id] : card === "one_to_many" ? [v?.to_node_id] : [v?.from_node_id, v?.to_node_id];
  const sides = {
    from_name: name(v?.from_node_id),
    to_name: name(v?.to_node_id),
    forward_name: v?.forward_name || "…",
    reverse_name: v?.reverse_name || "…",
  };
  const apiRule = { pattern: API_NAME, message: "Starts with a lowercase letter; letters, digits and underscores only (e.g. supplier, purchaseOrders)" };

  return (
    <Modal
      title={link ? "Edit link" : "New link"}
      open={open}
      onCancel={onClose}
      width={720}
      forceRender
      footer={
        <Space>
          {link && (
            <Button danger onClick={() => remove(false)}>
              Delete
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button type="primary" loading={save.isPending} onClick={() => form.submit()}>
            Save
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title={
          <span data-testid="link-preview">
            {forwardText(sides)} / {reverseText(sides)} <Tag>{CARD_SHORT[card]}</Tag>
          </span>
        }
        description="A link must read both ways: describe “who is what to whom” with a preposition/verb, e.g. PurchaseOrder belongs to Supplier / Supplier supplies PurchaseOrder."
      />
      <Form
        form={form}
        layout="vertical"
        onFinish={(values) =>
          save.mutate({
            ...values,
            forward_api_name: values.forward_api_name || undefined,
            reverse_api_name: values.reverse_api_name || undefined,
            fk_attribute_id: card === "many_to_many" ? null : values.fk_attribute_id || null,
            via_node_id: card === "many_to_many" ? values.via_node_id || null : null,
            via_from_attribute_id: card === "many_to_many" ? values.via_from_attribute_id || null : null,
            via_to_attribute_id: card === "many_to_many" ? values.via_to_attribute_id || null : null,
          })
        }
      >
        <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }} align="start">
          <Form.Item name="from_node_id" label="Source entity" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={entityOptions} />
          </Form.Item>
          <Form.Item name="forward_name" label="Forward name (source → target)" rules={[{ required: true, max: 50 }]}>
            <Input placeholder="e.g. belongs to, pays" />
          </Form.Item>
          <Form.Item name="to_node_id" label="Target entity" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={entityOptions} />
          </Form.Item>
        </Space>
        <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }} align="start">
          <Form.Item name="reverse_name" label="Reverse name (target → source)" rules={[{ required: true, max: 50 }]}>
            <Input placeholder="e.g. supplies, receives" />
          </Form.Item>
          <Form.Item name="forward_api_name" label="Forward API name (property on the source)" rules={[apiRule]}>
            <Input placeholder="e.g. supplier" />
          </Form.Item>
          <Form.Item name="reverse_api_name" label="Reverse API name (property on the target)" rules={[apiRule]}>
            <Input placeholder="e.g. purchaseOrders" />
          </Form.Item>
        </Space>
        <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }} align="start">
          <Form.Item name="cardinality" label="Cardinality" rules={[{ required: true }]}>
            <Select options={Object.entries(CARD_LABEL).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item name="required" label="Required (the source must link to one target)" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Space>
        {card !== "many_to_many" ? (
          <Form.Item
            name="fk_attribute_id"
            label="Foreign-key field (same name as the API/code field, e.g. supplier_id, order_id)"
            extra="When empty, the field of type “reference” pointing to the other side is chosen automatically"
          >
            <Select allowClear showSearch optionFilterProp="label" options={fieldsOf(fkOwners)} />
          </Form.Item>
        ) : (
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }} align="start">
            <Form.Item name="via_node_id" label="Junction entity (optional, e.g. OrderLine)">
              <Select allowClear showSearch optionFilterProp="label" options={entityOptions} />
            </Form.Item>
            <Form.Item name="via_from_attribute_id" label={`Junction entity → ${sides.from_name} foreign key`}>
              <Select allowClear options={fieldsOf([v?.via_node_id])} disabled={!v?.via_node_id} />
            </Form.Item>
            <Form.Item name="via_to_attribute_id" label={`Junction entity → ${sides.to_name} foreign key`}>
              <Select allowClear options={fieldsOf([v?.via_node_id])} disabled={!v?.via_node_id} />
            </Form.Item>
          </Space>
        )}
        <Form.Item name="description" label="description">
          <Input.TextArea rows={2} placeholder="e.g. Each purchase order has exactly one supplier" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** All relations of the system: both readings, cardinality, key. */
export function LinksTable({ links, loading, onOpen, error, onRetry }: { links?: Link[]; loading?: boolean; onOpen: (l: Link) => void; error?: boolean; onRetry?: () => void }) {
  return (
    <ListTable<Link>
      error={error}
      onRetry={onRetry}
      label="Model links"
      size="small"
      rowKey="id"
      loading={loading}
      dataSource={links}
      locale={{ emptyText: "No links yet; click “New link”, or choose “reference” for an entity field and accept the suggestion" }}
      onRow={(row) => ({ onClick: () => onOpen(row), style: { cursor: "pointer" } })}
      columns={[
        { title: "Forward", render: (_, l) => forwardText(l) },
        { title: "Reverse", render: (_, l) => reverseText(l) },
        { title: "Cardinality", width: 70, render: (_, l) => <Tag color="purple">{CARD_SHORT[l.cardinality]}</Tag> },
        {
          title: "Foreign key / junction entity",
          render: (_, l) =>
            l.via_name ? (
              `${l.via_name} (${l.via_from_field || "?"} / ${l.via_to_field || "?"})`
            ) : l.fk_field ? (
              l.fk_field
            ) : (
              <Typography.Text type="secondary">Not set</Typography.Text>
            ),
        },
        { title: "Required", width: 60, render: (_, l) => (l.required ? "yes" : "no") },
        {
          title: "API name",
          render: (_, l) => [l.forward_api_name, l.reverse_api_name].filter(Boolean).join(" / ") || "—",
        },
        { title: "description", dataIndex: "description", ellipsis: true },
      ]}
    />
  );
}
