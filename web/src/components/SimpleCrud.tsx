import type { TableProps } from "antd";
import { ListTable } from "./ListView";
import { PlusOutlined } from "@ant-design/icons";
import { Button, Form, Modal, Popconfirm, Space, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState, type ReactNode } from "react";

import { EmptyState } from "./EmptyState";

/** Table + create/edit modal used by small registries (environments, modules, APIs, people). */
export function SimpleCrud<T extends { id: string }>(props: {
  title: string;
  rows?: T[];
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
  total?: number;
  filtered?: boolean;
  columns: ColumnsType<T>;
  fields: ReactNode;
  onCreate: (values: Record<string, unknown>) => Promise<unknown>;
  onUpdate?: (row: T, values: Record<string, unknown>) => Promise<unknown>;
  onDelete?: (row: T) => void;
  deleteLabel?: string;
  extraActions?: (row: T) => ReactNode;
  expandable?: TableProps<T>["expandable"];
  /** helpful empty state */
  emptyTitle?: string;
  emptyHint?: ReactNode;
}) {
  const [editing, setEditing] = useState<T | null | undefined>(undefined);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const open = (row: T | null) => {
    setEditing(row);
    form.resetFields();
    if (row) form.setFieldsValue(row);
  };
  const submit = async (values: Record<string, unknown>) => {
    setSaving(true);
    try {
      if (editing && props.onUpdate) await props.onUpdate(editing, values);
      else await props.onCreate(values);
      setEditing(undefined);
    } catch {
      /* error toast shown by the mutation */
    } finally {
      setSaving(false);
    }
  };
  return (
    <>
      <Space style={{ marginBottom: 12, width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={5} style={{ margin: 0 }}>
          {props.title}
        </Typography.Title>
        <Button size="small" icon={<PlusOutlined />} onClick={() => open(null)}>
          Add
        </Button>
      </Space>
      <ListTable<T>
        error={props.error}
        onRetry={props.onRetry}
        total={props.total}
        filtered={props.filtered}
        label={props.title}
        size="small"
        rowKey="id"
        loading={props.loading}
        dataSource={props.rows}

        expandable={props.expandable}
        locale={
          props.emptyTitle
            ? { emptyText: <EmptyState title={props.emptyTitle} hint={props.emptyHint} actionLabel={`Add ${props.title.replace(/ \(.*$/, "")}`} onAction={() => open(null)} /> }
            : undefined
        }
        columns={[
          ...props.columns,
          {
            title: "Action",
            width: 200,
            render: (_, row) => (
              <Space>
                {props.extraActions?.(row)}
                {props.onUpdate && <a onClick={() => open(row)}>Edit</a>}
                {props.onDelete && (
                  <Popconfirm title={`${props.deleteLabel || "Delete"}? `} onConfirm={() => props.onDelete!(row)}>
                    <a>{props.deleteLabel || "Delete"}</a>
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={editing ? `Edit ${props.title}` : `Add ${props.title}`}
        open={editing !== undefined}
        onCancel={() => setEditing(undefined)}
        onOk={() => form.submit()}
        confirmLoading={saving}
        destroyOnHidden
        forceRender
      >
        <Form form={form} layout="vertical" onFinish={submit}>
          {props.fields}
        </Form>
      </Modal>
    </>
  );
}
