import { Button, Space, Table, Typography, type TableProps } from "antd";
import { useEffect, useRef } from "react";

export const LIST_HEIGHT = "min(52vh, 560px)";

export function listTitle(label: string, count: number | undefined) {
  return `${label} (${count ?? "…"})`;
}

export function ListCount({ label, count, total, filtered, error, onRetry }: {
  label: string; count?: number; total?: number; filtered?: boolean; error?: boolean; onRetry?: () => void;
}) {
  const text = count === undefined ? error ? "Count unavailable" : "Loading items…"
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
export function ListTable<T extends object>({ label, total, filtered, error, onRetry, ...props }: TableProps<T> & {
  label: string; total?: number; filtered?: boolean; error?: boolean; onRetry?: () => void;
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
    <div ref={root}>
      <Table<T>
        {...props}
        locale={{ ...props.locale, ...(count === undefined ? { emptyText: error ? "List unavailable" : "Loading items…" } : {}) }}
        scroll={{ x: "max-content", y: LIST_HEIGHT, ...props.scroll }}
        pagination={props.pagination ?? { pageSize: 50, hideOnSinglePage: true }}
        title={() => <Typography.Text strong role="status" aria-label={`${label} count`}>{listTitle(label, count)}</Typography.Text>}
        footer={() => <ListCount label={label} count={count} total={total} filtered={filtered} error={error} onRetry={onRetry} />}
      />
    </div>
  );
}
