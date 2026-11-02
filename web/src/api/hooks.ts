import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { App } from "antd";

import { describeError } from "./client";

/** Mutation with uniform error toast and cache invalidation. */
export function useApiMutation<TVars, TResult = unknown>(
  fn: (vars: TVars) => Promise<TResult>,
  opts: { invalidate?: QueryKey[]; success?: string; onSuccess?: (r: TResult, v: TVars) => void } = {},
) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result, vars) => {
      for (const key of opts.invalidate || []) qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["progress"] }); // main-flow step bar
      if (opts.success) message.success(opts.success);
      opts.onSuccess?.(result, vars);
    },
    onError: (err) => {
      message.error(describeError(err));
    },
  });
}
