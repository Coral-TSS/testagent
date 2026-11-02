import { App, Input, List, Select, Space, Tag, Typography } from "antd";
import { useState } from "react";

import { api, describeError } from "../api/client";
import type { DataType, Suggestion } from "../api/types";
import { DATA_TYPE_LABEL } from "./EntityFields";
import { CARD_LABEL, CARD_SHORT, effectText, preconditionText } from "./links";

const ATTR: Record<string, string> = { conditions: "Conditions", states: "Status", constraints: "Constraints" };
const KIND: Record<string, string> = { entity: "entities", action: "Actions", relation: "Link" };

export function describeSuggestion(s: Suggestion): string {
  const p = s.payload;
  if (s.kind === "node") return `Add ${KIND[p.node_kind || ""] || "Node"}“${p.name}”`;
  const owner = p.node_name || "(unknown node)"; // the server fills node_name; never show a UUID
  if (s.kind === "field") {
    const type = p.data_type ? `, ${DATA_TYPE_LABEL[p.data_type as DataType] || p.data_type}` : "";
    const values = p.enum_values?.length ? ` (${p.enum_values.join("/")})` : "";
    const unit = p.unit ? `, unit ${p.unit}` : "";
    if (p.rename_from)
      return `“${owner}” field ${p.rename_from} renamed to ${p.name} (same as the API field, links kept)${type}${values}${unit}`;
    return `Add to “${owner}” new field ${p.name}${p.display_name ? ` (${p.display_name})` : ""}${type}${values}${unit}`;
  }
  if (s.kind === "link") {
    const from = p.from_name || "?";
    const to = p.to_name || "?";
    const card = p.cardinality ? CARD_SHORT[p.cardinality] : "N:1";
    const fk = p.fk_field ? `, foreign key ${p.fk_field}` : "";
    return `New link “${from} ${p.forward_name || "related"} ${to}” / “${to} ${p.reverse_name || "related"} ${from}” (${card}${fk})`;
  }
  if (s.kind === "rules") {
    const parts = [
      p.preconditions?.length ? `precondition ${p.preconditions.map(preconditionText).join("; ")}` : "",
      p.effects?.length ? `effect ${p.effects.map((e) => effectText(e)).join("; ")}` : "",
    ].filter(Boolean);
    return `Add to action “${owner}”: ${parts.join("; ")}`;
  }
  if (s.kind === "io") {
    const parts = [
      p.description ? `purpose: ${p.description}` : "",
      p.inputs?.length ? `inputs ${p.inputs.map((x) => x.name).join(", ")}` : "",
      p.outputs?.length ? `outputs ${p.outputs.map((x) => x.name).join(", ")}` : "",
    ].filter(Boolean);
    return `Add to action “${owner}”: ${parts.join("; ") || "inputs/outputs"}`;
  }
  return `Add to “${owner}”: ${ATTR[p.attr || ""] || p.attr}: ${p.text}`;
}

/** Accept/reject model suggestions (human-only; agent output never lands without this). */
export function SuggestionList({ items, onChanged }: { sutId: string; items: Suggestion[]; onChanged: () => void }) {
  const { message, modal } = App.useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (id: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(id);
    try {
      await fn();
      message.success(ok);
      onChanged();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setBusy(null);
    }
  };
  const reject = (s: Suggestion) => {
    let reason = "";
    modal.confirm({
      title: "Reject suggestion",
      content: <Input.TextArea placeholder="Reason (optional, used to steer later suggestions)" onChange={(e) => (reason = e.target.value)} />,
      onOk: () => run(s.id, () => api(`/suggestions/${s.id}/reject`, { method: "POST", body: { reason: reason || null } }), "Rejected"),
    });
  };
  const accept = (s: Suggestion) => {
    if (s.kind === "link") {
      const p = s.payload;
      const initial = {
        forward_name: p.forward_name || "belongs to",
        reverse_name: p.reverse_name || "has",
        forward_api_name: p.forward_api_name || undefined,
        reverse_api_name: p.reverse_api_name || undefined,
        cardinality: p.cardinality || "many_to_one",
      };
      const v: Record<string, string | undefined> = { ...initial };
      const set = (k: string) => (e: { target: { value: string } }) => (v[k] = e.target.value.trim() || undefined);
      modal.confirm({
        title: "Accept link suggestion (edit the readings first if needed)",
        width: 560,
        content: (
          <Space orientation="vertical" style={{ width: "100%", marginTop: 12 }}>
            <span>
              {p.from_name} <Input size="small" style={{ width: 120 }} defaultValue={initial.forward_name} onChange={set("forward_name")} aria-label="Forward name" /> {p.to_name}
            </span>
            <span>
              {p.to_name} <Input size="small" style={{ width: 120 }} defaultValue={initial.reverse_name} onChange={set("reverse_name")} aria-label="Reverse name" /> {p.from_name}
            </span>
            <span>
              API names: 
              <Input size="small" style={{ width: 140 }} defaultValue={initial.forward_api_name} onChange={set("forward_api_name")} /> /{" "}
              <Input size="small" style={{ width: 140 }} defaultValue={initial.reverse_api_name} onChange={set("reverse_api_name")} />
            </span>
            <Select
              size="small"
              style={{ width: 260 }}
              defaultValue={initial.cardinality}
              onChange={(c) => (v.cardinality = c)}
              options={Object.entries(CARD_LABEL).map(([value, label]) => ({ value, label }))}
            />
            {p.fk_field && <Typography.Text type="secondary">foreign key {p.fk_field}</Typography.Text>}
          </Space>
        ),
        onOk: () => {
          if (!v.forward_name || !v.reverse_name) {
            message.error("Both direction names are required");
            return Promise.reject(new Error("names required"));
          }
          return run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: v }), "Accepted and link created");
        },
      });
      return;
    }
    if (s.kind !== "node") {
      run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: {} }), "Accepted");
      return;
    }
    let name = s.payload.name || "";
    modal.confirm({
      title: "Accept and create node",
      content: <Input defaultValue={name} onChange={(e) => (name = e.target.value)} />,
      onOk: () => run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: { name } }), "Accepted and node created"),
    });
  };
  return (
    <List
      size="small"
      dataSource={items}
      locale={{ emptyText: "No suggestions" }}
      renderItem={(s) => (
        <List.Item
          actions={
            s.status === "pending"
              ? [
                  <a key="a" onClick={() => accept(s)} aria-disabled={busy === s.id}>
                    Accept
                  </a>,
                  <a key="r" onClick={() => reject(s)}>
                    Reject
                  </a>,
                ]
              : [<Tag key="s">{s.status === "accepted" ? "Accepted" : "Rejected"}</Tag>]
          }
        >
          <Space direction="vertical" size={0}>
            <span>
              {s.requirement_code && <Tag>{s.requirement_code}</Tag>}
              {describeSuggestion(s)}
            </span>
            {s.reason && <Typography.Text type="secondary">{s.reason}</Typography.Text>}
            {s.payload.reason && s.payload.reason !== s.reason && (
              <Typography.Text type="secondary">{s.payload.reason}</Typography.Text>
            )}
          </Space>
        </List.Item>
      )}
    />
  );
}
