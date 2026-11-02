import { useQuery } from "@tanstack/react-query";
import { Card, Empty, Select, Typography } from "antd";
import { useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Sut } from "../api/types";
import { CaseList } from "../components/CaseList";

/** Case library (SUT scope); generation/coverage/export within a version are on the version page “Test cases” tab. */
export function CasesPage() {
  const params = useParams();
  const [search, setSearch] = useSearchParams();
  const suts = useQuery({ queryKey: ["suts"], queryFn: () => api<Sut[]>("/suts"), enabled: !params.sutId });
  const sutId = params.sutId || search.get("sut") || search.get("sut_id") || undefined;
  return (
    <Card>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        Test cases
      </Typography.Title>
      {!params.sutId && (
        <Select
          placeholder="Choose SUT"
          style={{ width: 240, marginBottom: 16 }}
          value={sutId}
          onChange={(v) => setSearch({ sut: v })}
          options={(suts.data || []).map((s) => ({ value: s.id, label: `${s.code} ${s.name}` }))}
        />
      )}
      {sutId ? <CaseList sutId={sutId} versionId={search.get("version_id") || undefined} /> : <Empty description="Choose a SUT at the top right or here first; cases belong to a SUT" />}
    </Card>
  );
}
