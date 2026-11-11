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

export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0)
      return "Sem conexão com o assistente. Confira sua internet e tente de novo.";
    if (err.status === 422)
      return "Não consegui entender essa mensagem. Use de 1 a 1000 caracteres e tente de novo.";
    if (err.status === 429)
      return "Muitas perguntas seguidas. Aguarde um instante e tente de novo.";
    if (err.status >= 500)
      return "O assistente está indisponível agora. Tente de novo em instantes.";
    return err.message;
  }
  if (err instanceof StreamError) {
    return err.kind === "server"
      ? "O assistente está indisponível agora. Tente de novo em instantes."
      : err.message;
  }
  return "Algo deu errado com o assistente. Tente de novo.";
}

const ORDINALS = ["primeira", "segunda", "terceira"];
export const ordinal = (n: number) => ORDINALS[n] ?? `${n + 1}ª`;
