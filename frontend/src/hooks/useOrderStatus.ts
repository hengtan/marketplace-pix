import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { api, isPaymentPending } from "@/api/endpoints";
import type { Order, Payment } from "@/api/schemas";
import { qk } from "./queries";

export const ORDER_POLL_MS = 2000;

export interface OrderStatusResult {
  order: Order | undefined;
  payment: Payment | undefined;
  isLoading: boolean;
  isLive: boolean;
  error: Error | null;
}

/**
 * Single source of truth for the live state of an order. Today it polls the REST
 * endpoints while the order is PENDING; swapping to SSE only requires changing this hook.
 */
export function useOrderStatus(orderId: string, intervalMs = ORDER_POLL_MS): OrderStatusResult {
  const orderQuery = useQuery({
    queryKey: qk.order(orderId),
    queryFn: () => api.order(orderId),
    refetchInterval: (q) =>
      q.state.data && q.state.data.status !== "PENDING" ? false : intervalMs,
    staleTime: 0,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });

  const status = orderQuery.data?.status;
  const paymentQuery = useQuery({
    queryKey: qk.payment(orderId),
    queryFn: () => api.paymentByOrder(orderId),
    enabled: Boolean(orderQuery.data),
    refetchInterval: (q) => {
      const data = q.state.data;
      if (isPaymentPending(data)) return Math.max(500, (data.retryAfter ?? 1) * 1000);
      if (status && status !== "PENDING" && data) return false;
      return intervalMs;
    },
    staleTime: 0,
    retry: false,
  });

  return {
    order: orderQuery.data,
    payment: isPaymentPending(paymentQuery.data) ? undefined : paymentQuery.data,
    isLoading: orderQuery.isLoading,
    isLive: status === "PENDING",
    error: orderQuery.error,
  };
}
