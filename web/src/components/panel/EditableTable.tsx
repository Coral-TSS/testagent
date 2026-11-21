import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import type { ReactNode } from "react";

import { EmptyState } from "../EmptyState";
import { ListTable } from "../ListView";

export interface EditableColumn<T> {
  title: string;
  width?: number | string;
  render: (row: T, index: number) => ReactNode;
}

/** A collection edited in place: headers, an add-row button, and optional rarely used fields in the expand row. */
export function EditableTable<T>({
  label,
  rows,
  rowKey,
  columns,
  extra,
  onRemove,
  removeLabel,
  onAdd,
  addLabel = "添加一行",
  emptyText = "还没有内容",
}: {
  label: string;
  rows: T[];
  rowKey: (row: T, index: number) => string;
  columns: EditableColumn<T>[];
  extra?: (row: T, index: number) => ReactNode;
  onRemove?: (index: number) => void;
  removeLabel?: (row: T) => string;
  onAdd?: () => void;
  addLabel?: string;
  emptyText?: string;
}) {
  const keyed = rows.map((row, index) => ({ row, index, key: rowKey(row, index) }));
  return (
    <div>
      <ListTable<{ row: T; index: number; key: string }>
        label={label}
        size="small"
        rowKey="key"
        dataSource={keyed}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        locale={{
          emptyText: onAdd ? (
            <EmptyState title={emptyText} actionLabel={addLabel} onAction={onAdd} />
          ) : (
            emptyText
          ),
        }}
        expandable={
          extra
            ? {
                rowExpandable: () => true,
                expandedRowRender: (item) => <div style={{ paddingRight: 8 }}>{extra(item.row, item.index)}</div>,
              }
            : undefined
        }
        columns={[
          ...columns.map((col) => ({
            title: col.title,
            width: col.width,
            render: (_: unknown, item: { row: T; index: number }) => col.render(item.row, item.index),
          })),
          ...(onRemove
            ? [
                {
                  title: "",
                  width: 48,
                  render: (_: unknown, item: { row: T; index: number }) => (
                    <Tooltip title="删除">
                      <Button
                        type="text"
                        size="small"
                        danger
                        aria-label={removeLabel?.(item.row) || "删除"}
                        icon={<DeleteOutlined />}
                        onClick={() => onRemove(item.index)}
                      />
                    </Tooltip>
                  ),
                },
              ]
            : []),
        ]}
      />
      {onAdd && rows.length > 0 && (
        <Button type="dashed" size="small" icon={<PlusOutlined />} style={{ marginTop: 8 }} onClick={onAdd}>
          {addLabel}
        </Button>
      )}
    </div>
  );
}
