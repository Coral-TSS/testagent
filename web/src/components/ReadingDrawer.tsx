import { Drawer, type DrawerProps } from "antd";

import { useRememberedWidth } from "./panel/width";

type Kind = "requirement" | "node" | "agent";

/** One reading layout for the platform's right-side detail drawers. */
export function ReadingDrawer({ kind, children, rootClassName, ...props }: Omit<DrawerProps, "size" | "placement" | "resizable" | "drawerRender"> & { kind: Kind }) {
  const width = useRememberedWidth(`testagent:drawer-width:${kind}`, (viewport) => viewport * 0.6);
  return (
    <Drawer
      {...props}
      placement="right"
      size={width.compact ? width.width : width.width}
      rootClassName={["reading-drawer", width.resizing && "reading-drawer-resizing", rootClassName].filter(Boolean).join(" ")}
      drawerRender={(panel) => (
        <>
          {width.handle}
          {panel}
        </>
      )}
    >
      {children}
    </Drawer>
  );
}
