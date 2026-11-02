import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Space, Tag, Tooltip } from "antd";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Environment, EnvironmentCheck } from "../api/types";

export function useEnvironmentCheck(envId?: string) {
  return useQuery({
    queryKey: ["env-check", envId],
    queryFn: () => api<EnvironmentCheck>(`/environments/${envId}/check`),
    enabled: Boolean(envId),
    refetchInterval: (q) => (q.state.data?.reachable ? 30000 : 10000),
  });
}

function StartButton({ env }: { env: Environment }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const start = useApiMutation(() => api<{ reachable: boolean; message: string }>(`/environments/${env.id}/start`, { method: "POST" }), {
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["env-check", env.id] });
      if (r.reachable) message.success(`Environment “${env.name}” is reachable`);
      else message.warning(r.message);
    },
  });
  return (
    <Button size="small" type="primary" loading={start.isPending} onClick={() => start.mutate(undefined)}>
      Start
    </Button>
  );
}

/** Environment reachability: a small tag in tables (compact) or a page alert (only when unreachable). */
export function EnvironmentStatus({ env, compact = false }: { env?: Environment; compact?: boolean }) {
  const check = useEnvironmentCheck(env?.id);
  if (!env || !check.data) return null;
  if (compact)
    return check.data.reachable ? (
      <Tag color="green">Reachable</Tag>
    ) : (
      <Space size={4}>
        <Tooltip title={check.data.message}>
          <Tag color="red">unreachable</Tag>
        </Tooltip>
        {env.start_command && <StartButton env={env} />}
      </Space>
    );
  if (check.data.reachable) return null;
  return (
    <Alert
      type="warning"
      showIcon
      title={`SUT environment “${env.name}” is unreachable`}
      description={check.data.message}
      action={env.start_command ? <StartButton env={env} /> : undefined}
    />
  );
}
