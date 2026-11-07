import { Button, Space, Table, Typography, type TableProps } from "antd";
import { useEffect, useRef, type ReactNode } from "react";

export const LIST_HEIGHT = "min(52vh, 560px)";

export function listTitle(label: string, count: number | undefined) {
  return `${label} (${count ?? "…"})`;
}

export function ListCount({ label, count, total, filtered, error, onRetry, recordLimit }: {
  label: string; count?: number; total?: number; filtered?: boolean; error?: boolean; onRetry?: () => void; recordLimit?: number;
}) {
  const text = count === undefined ? error ? "Count unavailable" : "Loading items…"
    : recordLimit ? `Loaded ${count} recent ${count === 1 ? "record" : "records"} (up to ${recordLimit})`
    : filtered ? total !== undefined && total >= count ? `${count} / ${total} total` : `${count} matching items · total unavailable`
      : `Total ${count} ${count === 1 ? "item" : "items"}`;
  return (
    <Space wrap role="status" aria-label={`${label} total`}>
      <Typography.Text type="secondary">{text}</Typography.Text>
      {error && count !== undefined && <Typography.Text type="warning">Refresh failed; last loaded information may be out of date.</Typography.Text>}
      {error && onRetry && <Button size="small" onClick={onRetry}>Retry {label}</Button>}
    </Space>
  );
}

/** Callers supply filtered rows; counts cover every row, independently of the current page. */
export function ListTable<T extends object>({ label, total, filtered, error, onRetry, recordLimit, ...props }: TableProps<T> & {
  label: string; total?: number; filtered?: boolean; error?: boolean; onRetry?: () => void; recordLimit?: number;
}) {
  const root = useRef<HTMLDivElement>(null);
  const count = props.dataSource?.length;
  useEffect(() => {
    // AntD does not expose attributes for its scroll body; make that region keyboard reachable.
    const body = root.current?.querySelector(".ant-table-body");
    body?.setAttribute("tabindex", "0");
    body?.setAttribute("role", "region");
    body?.setAttribute("aria-label", `${label} rows`);
  }, [label]);
  return (
    <div ref={root} className="list-table">
      <Table<T>
        {...props}
        locale={{ ...props.locale, ...(count === undefined ? { emptyText: error ? "List unavailable" : "Loading items…" } : {}) }}
        scroll={{ x: "max-content", y: LIST_HEIGHT, ...props.scroll }}
        pagination={props.pagination ?? { pageSize: 50, hideOnSinglePage: true }}
        title={(data) => <Space orientation="vertical" size={4} style={{ width: "100%" }}>
          <Typography.Text strong role="status" aria-label={`${label} count`}>{listTitle(label, count)}</Typography.Text>
          {props.title?.(data)}
        </Space>}
        footer={(data) => <Space orientation="vertical" size={4} style={{ width: "100%" }}>
          {props.footer?.(data)}
          <ListCount label={label} count={count} total={total} filtered={filtered} error={error} onRetry={onRetry} recordLimit={recordLimit} />
        </Space>}
      />
    </div>
  );
}

/** Lists made of cards or text share the same bounded, keyboard-scrollable region. */
export function ListSection({ label, count, total, filtered, error, onRetry, recordLimit, children }: {
  label: string; count?: number; total?: number; filtered?: boolean; error?: boolean; onRetry?: () => void; recordLimit?: number; children: ReactNode;
}) {
  return (
    <section>
      <Typography.Text strong role="status" aria-label={`${label} count`}>{listTitle(label, count)}</Typography.Text>
      <div className="list-region" role="region" aria-label={`${label} rows`} tabIndex={0} style={{ maxHeight: LIST_HEIGHT, overflowY: "auto" }}>
        {count === undefined ? <Typography.Text type="secondary">{error ? "List unavailable" : "Loading items…"}</Typography.Text> : children}
      </div>
      <ListCount label={label} count={count} total={total} filtered={filtered} error={error} onRetry={onRetry} recordLimit={recordLimit} />
    </section>
  );
}
