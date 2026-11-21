import { ListTable } from "./ListView";
import { EditableTable } from "./panel/EditableTable";
import { Input, Select, Space, Switch, Tag, Typography } from "antd";
import type { ReactNode } from "react";

import type { DataType, IoLocation, IoParam } from "../api/types";
import { DATA_TYPE_OPTIONS, LOCATION_LABEL, typeText } from "./dataTypes";

export interface FieldOption {
  value: string;
  label: string;
}

/** Type cell: an enum shows its values. */
export function TypeTag({ p }: { p: { data_type: string; enum_values?: string[] | null } }) {
  return (
    <Space size={2} wrap>
      <Tag color="blue">{typeText(p.data_type)}</Tag>
      {p.data_type === "enum" && (p.enum_values || []).length > 0 && (
        <Typography.Text type="secondary">{(p.enum_values || []).join(" / ")}</Typography.Text>
      )}
    </Space>
  );
}

/**
 * Inputs / outputs. Read-only rows show the full detail. With `onChange` the same columns
 * are edited in place; format, example and the mapped field sit in the expand row.
 */
export function IoParamsTable(props: {
  label?: string;
  value?: IoParam[];
  onChange?: (next: IoParam[]) => void;
  showLocation?: boolean;
  locations?: IoLocation[];
  fieldOptions?: FieldOption[];
  emptyText?: string;
  addLabel?: string;
}) {
  const params = props.value || [];
  const editable = Boolean(props.onChange);
  const label = props.label || "参数";
  const locations = props.locations || (Object.keys(LOCATION_LABEL) as IoLocation[]);
  const fieldLabel = new Map((props.fieldOptions || []).map((f) => [f.value, f.label]));

  if (!editable) {
    return (
      <ListTable<IoParam & { _i: number }>
        label={label}
        size="small"
        rowKey="_i"
        dataSource={params.map((p, i) => ({ ...p, _i: i }))}
        locale={{ emptyText: props.emptyText || "未填写" }}
        columns={[
          {
            title: "名称",
            width: 170,
            render: (_, p) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text code style={{ whiteSpace: "nowrap" }}>{p.name}</Typography.Text>
                {p.display_name && <Typography.Text type="secondary">{p.display_name}</Typography.Text>}
              </Space>
            ),
          },
          { title: "类型", width: 150, render: (_, p) => <TypeTag p={p} /> },
          {
            title: "必填",
            width: 56,
            render: (_, p) => (p.required ? <Tag color="red">必填</Tag> : <Typography.Text type="secondary">否</Typography.Text>),
          },
          ...(props.showLocation
            ? [{ title: "位置", width: 84, render: (_: unknown, p: IoParam) => (p.location ? LOCATION_LABEL[p.location] || p.location : "—") }]
            : []),
          {
            title: "格式 / 示例",
            width: 130,
            render: (_: unknown, p: IoParam) => (
              <Space orientation="vertical" size={0}>
                {p.format && <span>{p.format}</span>}
                {p.example && <Typography.Text type="secondary">例如 {p.example}</Typography.Text>}
                {!p.format && !p.example && "—"}
              </Space>
            ),
          },
          { title: "映射字段", width: 130, render: (_: unknown, p: IoParam) => (p.field ? <Tag color="purple">{p.field}</Tag> : "—") },
          { title: "描述", dataIndex: "description", render: (d) => d || "—" },
        ]}
      />
    );
  }

  const update = (index: number, patch: Partial<IoParam>) => {
    props.onChange?.(params.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };
  const add = () => props.onChange?.([...params, { name: "", data_type: "string", required: false, location: locations[0] }]);
  return (
    <EditableTable<IoParam>
      label={label}
      rows={params}
      rowKey={(row, index) => `${row.name}:${index}`}
      emptyText={props.emptyText || "还没有参数"}
      addLabel={props.addLabel || "添加一行"}
      onAdd={add}
      onRemove={(index) => props.onChange?.(params.filter((_, i) => i !== index))}
      removeLabel={(row) => `删除 ${row.name || "参数"}`}
      columns={[
        { title: "名称", width: 150, render: (row, index) => <Input value={row.name} placeholder="字段名" onChange={(e) => update(index, { name: e.target.value })} /> },
        {
          title: "类型",
          width: 140,
          render: (row, index) => (
            <Select
              style={{ width: "100%" }}
              value={row.data_type}
              options={DATA_TYPE_OPTIONS}
              onChange={(data_type: DataType) => update(index, { data_type })}
            />
          ),
        },
        { title: "必填", width: 64, render: (row, index) => <Switch checked={Boolean(row.required)} onChange={(required) => update(index, { required })} /> },
        ...(props.showLocation
          ? [{
              title: "位置",
              width: 120,
              render: (row: IoParam, index: number) => (
                <Select
                  allowClear
                  style={{ width: "100%" }}
                  value={row.location || undefined}
                  options={locations.map((l) => ({ value: l, label: LOCATION_LABEL[l] }))}
                  onChange={(location) => update(index, { location: location || null })}
                />
              ),
            }]
          : []),
      ]}
      extra={(row, index) => (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Labeled label="显示名"><Input value={row.display_name || ""} placeholder="例如 Amount" onChange={(e) => update(index, { display_name: e.target.value || null })} /></Labeled>
          <Labeled label="格式"><Input value={row.format || ""} placeholder="例如以分为单位的整数" onChange={(e) => update(index, { format: e.target.value || null })} /></Labeled>
          <Labeled label="示例"><Input value={row.example || ""} placeholder="例如 5000000" onChange={(e) => update(index, { example: e.target.value || null })} /></Labeled>
          {row.data_type === "enum" && (
            <Labeled label="枚举值">
              <Select mode="tags" style={{ width: "100%" }} value={row.enum_values || []} onChange={(enum_values) => update(index, { enum_values })} tokenSeparators={[","]} />
            </Labeled>
          )}
          {props.fieldOptions && (
            <Labeled label="映射字段">
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ width: "100%" }}
                value={row.attribute_id || undefined}
                options={props.fieldOptions}
                onChange={(attribute_id) => update(index, {
                  attribute_id: attribute_id || null,
                  field: attribute_id ? (fieldLabel.get(attribute_id) || "").split(" (")[0] : null,
                })}
              />
            </Labeled>
          )}
          <Labeled label="描述"><Input.TextArea value={row.description || ""} autoSize={{ minRows: 1 }} onChange={(e) => update(index, { description: e.target.value || null })} /></Labeled>
        </Space>
      )}
    />
  );
}

function Labeled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <Typography.Text type="secondary">{label}</Typography.Text>
      {children}
    </div>
  );
}
