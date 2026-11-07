import { App, Button, Checkbox, Input, List, Select, Space, Switch, Tag, Tooltip, Typography } from "antd";
import { useMemo, useState } from "react";

import { api, describeError } from "../api/client";
import type { AcceptBatchResult, CompletionOutcome, DataType, Suggestion, SuggestionSource } from "../api/types";
import { DATA_TYPE_LABEL } from "./EntityFields";
import { CARD_LABEL, CARD_SHORT, effectText, preconditionText } from "./links";
import { LIST_HEIGHT, ListCount, listTitle } from "./ListView";

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

/** #6: where a suggestion comes from → label and colour. */
export const SOURCE_TAG: Record<SuggestionSource, [string, string]> = {
  requirement: ["Requirement", "blue"],
  openapi: ["OpenAPI", "green"],
  model_rule: ["Model rule", "cyan"],
  ai_inferred: ["AI inferred", "orange"],
};

/** Pre-selected for "Accept selected": pending, not an AI inference, not a link (links need their names confirmed). */
export function defaultSelected(items: Suggestion[]): string[] {
  return items.filter((s) => s.status === "pending" && (s.source || "ai_inferred") !== "ai_inferred" && s.kind !== "link").map((s) => s.id);
}

const DROP_LABEL: Record<string, string> = {
  duplicate_node: "already in the model",
  duplicate_api: "API already bound to an action",
  duplicate_in_batch: "repeated in the same batch",
  previously_rejected: "rejected before",
  invalid: "no name or no description",
};

/** #4: "3 new suggestions, 4 left out (2 repeated in the same batch, 1 API already bound…)". */
export function completionNote(out: CompletionOutcome): string | null {
  if (!out.suggestions) return null;
  const parts = Object.entries(out.dropped || {})
    .filter(([, n]) => (n || 0) > 0)
    .map(([k, n]) => `${n} ${DROP_LABEL[k] || k}`);
  const skipped = out.skipped || 0;
  const pending = skipped - Object.values(out.dropped || {}).reduce((a, n) => a + (n || 0), 0);
  if (pending > 0) parts.push(`${pending} already pending`);
  return `${out.suggestions.length} new suggestion(s)${skipped ? `, ${skipped} left out (${parts.join(", ")})` : ""}`;
}

function SourceTag({ s }: { s: Suggestion }) {
  const source = s.source || "ai_inferred";
  const [label, color] = SOURCE_TAG[source];
  const text = source === "requirement" && s.requirement_code ? `${label} ${s.requirement_code}` : label;
  return (
    <Tooltip title={s.evidence ? `Basis: ${s.evidence}` : source === "ai_inferred" ? "No source: inferred by the AI" : undefined}>
      <Tag color={color}>{text}</Tag>
    </Tooltip>
  );
}

/** Accept/reject model suggestions (human-only; agent output never lands without this). */
export function SuggestionList({ sutId, items, onChanged, loading, error, onRetry }: {
  sutId: string; items: Suggestion[]; onChanged: () => void; loading?: boolean; error?: boolean; onRetry?: () => void;
}) {
  const { message, modal } = App.useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null);
  const [onlyAi, setOnlyAi] = useState(false);
  const pending = items.filter((s) => s.status === "pending");
  const selected = useMemo(() => (picked ?? defaultSelected(items)).filter((id) => pending.some((s) => s.id === id)), [picked, items, pending]);
  const shown = onlyAi ? items.filter((s) => (s.source || "ai_inferred") === "ai_inferred") : items;
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
  const inferred = (s: Suggestion) => (s.source || "ai_inferred") === "ai_inferred";
  type Dialog = { current: { update: (c: { okButtonProps: { disabled: boolean } }) => void } | null };
  /** an AI inference needs the person's reason (5+ characters): OK stays disabled until then */
  const noteField = (s: Suggestion, v: { note?: string }, dialog: Dialog) =>
    inferred(s) ? (
      <Input.TextArea
        aria-label="Why it is right"
        placeholder="AI inference without a source: why is it right? (5+ characters, kept in the change log)"
        onChange={(e) => {
          v.note = e.target.value.trim();
          dialog.current?.update({ okButtonProps: { disabled: v.note.length < 5 } });
        }}
        style={{ marginTop: 8 }}
      />
    ) : null;
  const gate = (s: Suggestion) => ({ okButtonProps: { disabled: inferred(s) } });
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
      const dialog: Dialog = { current: null };
      dialog.current = modal.confirm({
        ...gate(s),
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
            {noteField(s, v, dialog)}
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
      if (!inferred(s)) {
        run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: {} }), "Accepted");
        return;
      }
      const v: { note?: string } = {};
      const dialog: Dialog = { current: null };
      dialog.current = modal.confirm({
        ...gate(s),
        title: "Accept an AI inference",
        content: (
          <>
            <Typography.Paragraph style={{ marginBottom: 0 }}>{describeSuggestion(s)}</Typography.Paragraph>
            {noteField(s, v, dialog)}
          </>
        ),
        onOk: () => run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: v }), "Accepted"),
      });
      return;
    }
    const v: { name?: string; note?: string } = { name: s.payload.name || "" };
    const dialog: Dialog = { current: null };
    dialog.current = modal.confirm({
      ...gate(s),
      title: "Accept and create node",
      content: (
        <>
          <Input aria-label="Node name" defaultValue={v.name} onChange={(e) => (v.name = e.target.value)} />
          {s.payload.similar_to && <Typography.Text type="warning">Possible duplicate of “{s.payload.similar_to}”</Typography.Text>}
          {noteField(s, v, dialog)}
        </>
      ),
      onOk: () => run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: { name: v.name, ...(v.note ? { note: v.note } : {}) } }), "Accepted and node created"),
    });
  };
  const acceptSelected = async () => {
    setBusy("batch");
    try {
      const out = await api<AcceptBatchResult>(`/suts/${sutId}/suggestions/accept-batch`, { method: "POST", body: { ids: selected } });
      if (out.skipped.length) message.warning(`Accepted ${out.accepted.length}, skipped ${out.skipped.length}: ${[...new Set(out.skipped.map((x) => x.message))].join("; ")}`);
      else message.success(`Accepted ${out.accepted.length}`);
      setPicked(null);
      onChanged();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setBusy(null);
    }
  };
  const toggle = (id: string, on: boolean) => setPicked(on ? [...selected, id] : selected.filter((x) => x !== id));
  const aiCount = pending.filter(inferred).length;
  return (
    <>
      <Typography.Text strong role="status" aria-label="Model suggestions count">{listTitle("Model suggestions", loading || (error && !items.length) ? undefined : shown.length)}</Typography.Text>
      {pending.length > 0 && (
        <Space wrap style={{ marginBottom: 8 }} data-testid="suggestion-batch">
          <Button type="primary" size="small" disabled={!selected.length} loading={busy === "batch"} onClick={acceptSelected}>
            Accept selected ({selected.length})
          </Button>
          <Typography.Text type="secondary">AI inferences and links are not pre-selected: accept them one by one.</Typography.Text>
          {aiCount > 0 && (
            <Space size={4}>
              <Switch size="small" checked={onlyAi} onChange={setOnlyAi} aria-label="Only AI inferences" />
              <span>Only AI inferences ({aiCount})</span>
            </Space>
          )}
        </Space>
      )}
      <div role="region" aria-label="Model suggestions rows" tabIndex={0} style={{ maxHeight: LIST_HEIGHT, overflowY: "auto" }}>
      <List
        size="small"
        dataSource={shown}
        locale={{ emptyText: loading ? "Loading suggestions…" : error ? "Suggestions unavailable" : onlyAi ? "No suggestions match the filter" : "No suggestions" }}
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
            <Space align="start">
              {s.status === "pending" && (
                <Checkbox
                  aria-label={`Select ${describeSuggestion(s)}`}
                  checked={selected.includes(s.id)}
                  disabled={s.kind === "link" || inferred(s)}
                  onChange={(e) => toggle(s.id, e.target.checked)}
                />
              )}
              <Space orientation="vertical" size={0}>
                <span>
                  <SourceTag s={s} />
                  {s.source !== "requirement" && s.requirement_code && <Tag>{s.requirement_code}</Tag>}
                  {describeSuggestion(s)}
                  {s.payload.api && <Typography.Text code>{s.payload.api}</Typography.Text>}
                  {s.payload.similar_to && <Tag color="gold">Possible duplicate: {s.payload.similar_to}</Tag>}
                </span>
                {s.evidence && <Typography.Text type="secondary">Basis: {s.evidence}</Typography.Text>}
                {s.reason && <Typography.Text type="secondary">{s.reason}</Typography.Text>}
                {s.payload.reason && s.payload.reason !== s.reason && <Typography.Text type="secondary">{s.payload.reason}</Typography.Text>}
              </Space>
            </Space>
          </List.Item>
        )}
      />
      </div>
      <ListCount label="Model suggestions" count={loading || (error && !items.length) ? undefined : shown.length} total={items.length} filtered={onlyAi} error={error} onRetry={onRetry} />
    </>
  );
}
