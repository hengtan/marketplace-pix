import { ApiError } from "@/api/client";
import { StreamError } from "./api";

export const SUGGESTIONS = [
  "Quero um fone com cancelamento de ruído",
  "O que tem de esporte até R$ 100?",
  "Esse tem estoque?",
] as const;

export const MAX_MESSAGE_LENGTH = 1000;

const RUNNING: Record<string, string> = {
  search_products: "Consultando o catálogo...",
  get_stock: "Verificando o estoque...",
  get_order_status: "Consultando o pedido...",
};

const DONE: Record<string, string> = {
  search_products: "Catálogo consultado",
  get_stock: "Estoque verificado",
  get_order_status: "Pedido consultado",
};

const NAMES: Record<string, string> = {
  search_products: "Busca no catálogo",
  get_stock: "Consulta de estoque",
  get_order_status: "Consulta de pedido",
};

export const toolRunningLabel = (name: string) => RUNNING[name] ?? "Consultando uma ferramenta...";
export const toolDoneLabel = (name: string) => DONE[name] ?? "Ferramenta consultada";
export const toolTitle = (name: string) => NAMES[name] ?? name;

export const TIMEOUT_MESSAGE =
  "O assistente demorou demais para responder. Tente de novo em instantes.";

export interface Failure {
  message: string;
  retryAfter?: number;
  retryable: boolean;
}

export function formatWait(seconds: number): string {
  const s = Math.max(1, Math.ceil(seconds));
  if (s < 60) return `${s} ${s === 1 ? "segundo" : "segundos"}`;
  const minutes = Math.ceil(s / 60);
  if (minutes < 60) return `${minutes} ${minutes === 1 ? "minuto" : "minutos"}`;
  const hours = Math.ceil(minutes / 60);
  return `${hours} ${hours === 1 ? "hora" : "horas"}`;
}

const after = (retryAfter?: number) =>
  retryAfter ? `em ${formatWait(retryAfter)}` : "em instantes";

function budget(scope: string | undefined, retryAfter?: number): Failure {
  if (scope === "session") {
    return {
      message: `Esta conversa atingiu o limite de uso do assistente. Comece uma nova conversa${
        retryAfter ? ` ou tente de novo ${after(retryAfter)}` : ""
      }.`,
      retryAfter,
      retryable: false,
    };
  }
  return {
    message: `Você atingiu o limite de uso do assistente por hoje. Volte ${
      retryAfter ? after(retryAfter) : "amanhã"
    } ou siga explorando a vitrine.`,
    retryAfter,
    retryable: false,
  };
}

function unavailable(retryAfter?: number): Failure {
  return {
    message: `O assistente está indisponível agora. Tente de novo ${after(retryAfter)}.`,
    retryAfter,
    retryable: true,
  };
}

export function describeFailure(err: unknown): Failure {
  if (err instanceof ApiError) {
    if (err.status === 0) {
      return {
        message: "Sem conexão com o assistente. Confira sua internet e tente de novo.",
        retryable: true,
      };
    }
    if (err.status === 422) {
      return {
        message: "Não consegui entender essa mensagem. Use de 1 a 1000 caracteres e tente de novo.",
        retryable: true,
      };
    }
    if (err.status === 429) {
      if (/budget/i.test(err.message) || err.scope || err.limit) {
        return budget(err.scope, err.retryAfter);
      }
      return {
        message: `Muitas perguntas seguidas. Aguarde ${
          err.retryAfter ? formatWait(err.retryAfter) : "um instante"
        } e tente de novo.`,
        retryAfter: err.retryAfter,
        retryable: true,
      };
    }
    if (err.status >= 500) return unavailable(err.retryAfter);
    return { message: err.message, retryable: true };
  }
  if (err instanceof StreamError) {
    if (err.kind === "server") {
      if (/budget/i.test(err.message) || err.info.scope) {
        return budget(err.info.scope, err.info.retryAfter);
      }
      return unavailable(err.info.retryAfter);
    }
    return { message: err.message, retryable: true };
  }
  return { message: "Algo deu errado com o assistente. Tente de novo.", retryable: true };
}

export const describeError = (err: unknown): string => describeFailure(err).message;

export const DEGRADED_NOTICE =
  "O modelo do assistente está indisponível agora. Mostrei só o que a busca no catálogo encontrou.";

const ORDINALS = ["primeira", "segunda", "terceira"];
export const ordinal = (n: number) => ORDINALS[n] ?? `${n + 1}ª`;
