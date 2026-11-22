import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Version } from "../api/types";

/** System of the page: from `/suts/:sutId/...` or from the version on `/versions/:versionId/...`. */
export function usePageSut() {
  const { sutId: fromPath, versionId } = useParams();
  const version = useQuery({
    queryKey: ["version", versionId],
    queryFn: () => api<Version>(`/versions/${versionId}`),
    enabled: Boolean(versionId) && !fromPath,
    retry: false,
  });
  const sutId = fromPath || version.data?.sut_id || "";
  return { sutId, versionId, ready: Boolean(sutId), version: version.data, sealed: Boolean(version.data?.sealed) };
}
