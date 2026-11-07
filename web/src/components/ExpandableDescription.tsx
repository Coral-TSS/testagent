import { Button, Tooltip, Typography } from "antd";
import { useId, useState } from "react";

/** Keep table descriptions readable without stealing the row's open-detail action. */
export function ExpandableDescription({ text, name }: { text?: string | null; name: string }) {
  const id = useId();
  const [expandedText, setExpandedText] = useState<string | null>(null);
  if (!text?.trim()) return <Typography.Text type="secondary">—</Typography.Text>;
  const characters = Array.from(text);
  const long = characters.length > 160;
  const expanded = expandedText === text;
  const shown = long && !expanded ? characters.slice(0, 160).join("") + "…" : text;
  return <div className="expandable-description">
    <Tooltip title={long && !expanded ? <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{text}</span> : null} styles={{ root: { maxWidth: "min(80vw, 480px)" } }}>
      <span id={id}>{shown}</span>
    </Tooltip>
    {long && <Button
      type="link"
      size="small"
      aria-expanded={expanded}
      aria-controls={id}
      aria-label={`${expanded ? "Collapse" : "Expand"} description of ${name}`}
      onClick={(event) => { event.stopPropagation(); setExpandedText(expanded ? null : text); }}
    >{expanded ? "Show less" : "Show more"}</Button>}
  </div>;
}
