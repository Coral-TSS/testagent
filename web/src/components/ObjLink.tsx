import { CopyOutlined } from "@ant-design/icons";
import { App, Button, Tooltip, Typography } from "antd";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

/** "Name (code)" — the one readable form for related objects. */
export function objLabel(name?: string | null, code?: string | null): string {
  if (name && code) return `${name} (${code})`;
  return name || code || "";
}

/** Link to a related object, shown as "Name (code)". */
export function ObjLink({ to, name, code, children }: { to: string; name?: string | null; code?: string | null; children?: ReactNode }) {
  return <Link to={to}>{children ?? objLabel(name, code)}</Link>;
}

/** An absolute path with a copy button (test repo, scripts). */
export function PathText({ path, label = "Copy path" }: { path?: string | null; label?: string }) {
  const { message } = App.useApp();
  if (!path) return <Typography.Text type="secondary">-</Typography.Text>;
  return (
    <span>
      <Typography.Text code style={{ wordBreak: "break-all" }}>
        {path}
      </Typography.Text>
      <Tooltip title={label}>
        <Button
          size="small"
          type="text"
          aria-label={label}
          icon={<CopyOutlined />}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(path);
              message.success("Copied");
            } catch {
              message.info(path);
            }
          }}
        />
      </Tooltip>
    </span>
  );
}
