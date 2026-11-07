import { Drawer, type DrawerProps } from "antd";
import { useEffect, useRef, useState, type PointerEvent } from "react";

type Kind = "requirement" | "node" | "agent";
type Drag = { id: number; startX: number; startWidth: number; width: number; previous: number | null };

function readWidth(key: string): number | null {
  try {
    const raw = window.localStorage.getItem(key);
    const width = raw === null ? NaN : Number(raw);
    return Number.isFinite(width) && width > 0 ? width : null;
  } catch { return null; }
}

/** One reading layout for the platform's right-side detail drawers. */
export function ReadingDrawer({ kind, children, rootClassName, ...props }: Omit<DrawerProps, "size" | "placement" | "resizable" | "drawerRender"> & { kind: Kind }) {
  const storageKey = `testagent:drawer-width:${kind}`;
  const [preferred, setPreferred] = useState(() => readWidth(storageKey));
  const [viewport, setViewport] = useState(() => window.innerWidth);
  const [resizing, setResizing] = useState(false);
  const drag = useRef<Drag | null>(null);
  const compact = viewport < 768;
  const max = Math.max(0, viewport - 48);
  const min = Math.min(480, max);
  const clamp = (value: number) => Math.round(Math.max(min, Math.min(max, value)));
  const width = compact ? viewport : clamp(preferred ?? viewport * 0.6);

  useEffect(() => {
    const onResize = () => {
      if (drag.current) {
        setPreferred(drag.current.previous);
        drag.current = null;
        setResizing(false);
      }
      setViewport(window.innerWidth);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const remember = (value: number | null) => {
    setPreferred(value);
    try {
      if (value === null) window.localStorage.removeItem(storageKey);
      else window.localStorage.setItem(storageKey, String(value));
    } catch { /* Width adjustment remains usable when browser storage is disabled. */ }
  };
  const endDrag = (event: PointerEvent<HTMLDivElement>, cancelled: boolean) => {
    const current = drag.current;
    if (!current || current.id !== event.pointerId) return;
    drag.current = null;
    setResizing(false);
    if (cancelled) setPreferred(current.previous);
    else remember(current.width);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  return (
    <Drawer
      {...props}
      placement="right"
      size={width}
      rootClassName={["reading-drawer", resizing && "reading-drawer-resizing", rootClassName].filter(Boolean).join(" ")}
      drawerRender={(panel) => <>
        {!compact && <div
          className="drawer-width-handle"
          role="separator"
          tabIndex={0}
          aria-label="Resize drawer"
          aria-orientation="vertical"
          aria-valuemin={min}
          aria-valuemax={max}
          aria-valuenow={width}
          aria-valuetext={`${width} pixels`}
          aria-keyshortcuts="ArrowLeft ArrowRight Home End Enter"
          title="Drag to resize. Left/Right arrows adjust width; Home/End use limits; Enter resets."
          onKeyDown={(event) => {
            const next = event.key === "ArrowLeft" ? width + 32 : event.key === "ArrowRight" ? width - 32 : event.key === "Home" ? min : event.key === "End" ? max : undefined;
            if (event.key !== "Enter" && next === undefined) return;
            event.preventDefault();
            event.stopPropagation();
            remember(event.key === "Enter" ? null : clamp(next!));
          }}
          onPointerDown={(event) => {
            if (event.button !== 0 || drag.current) return;
            event.preventDefault();
            event.currentTarget.focus();
            event.currentTarget.setPointerCapture?.(event.pointerId);
            drag.current = { id: event.pointerId, startX: event.clientX, startWidth: width, width, previous: preferred };
            setResizing(true);
          }}
          onPointerMove={(event) => {
            const current = drag.current;
            if (!current || current.id !== event.pointerId) return;
            current.width = clamp(current.startWidth + current.startX - event.clientX);
            setPreferred(current.width);
          }}
          onPointerUp={(event) => endDrag(event, false)}
          onPointerCancel={(event) => endDrag(event, true)}
          onLostPointerCapture={(event) => endDrag(event, true)}
        />}
        {panel}
      </>}
    >{children}</Drawer>
  );
}
