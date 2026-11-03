import { Image, Skeleton } from "antd";
import { useEffect, useState } from "react";

import { fetchBlob } from "../api/client";

/** Screenshot from the artifact store, fetched as a blob (errors show a clear message instead of a broken image). */
export function ArtifactImage({ sha, alt, width = 240 }: { sha: string; alt: string; width?: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let objectUrl: string | null = null;
    let alive = true;
    fetchBlob(`/artifacts/${sha}`)
      .then((blob) => {
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [sha]);
  if (failed) return <span style={{ color: "#999" }}>Screenshot failed to load</span>;
  if (!url) return <Skeleton.Image active style={{ width, height: width * 0.6 }} />;
  return <Image src={url} alt={alt} width={width} />;
}
