import { ApiError } from "@/api/client";

export function writeErrorMessage(error: unknown, what: "catálogo" | "estoque"): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Sua sessão expirou. Entre de novo para continuar.";
    if (error.status === 403) {
      return what === "catálogo"
        ? "Sua conta não tem permissão para alterar o catálogo (escopo catalog:write:own) ou o produto é de outra loja."
        : "Sua conta não tem permissão para alterar este estoque (escopo stock:write:own) ou o produto é de outra loja.";
    }
    if (error.status === 404) return "O produto não existe mais. Atualize a lista.";
    if (error.status === 409) return "Já existe um produto com esse nome. Escolha outro nome.";
    if (error.status === 422)
      return "Algum campo está inválido. Confira os valores e tente de novo.";
    if (error.status === 429) return "Muitas alterações em pouco tempo. Aguarde um instante.";
    if (error.status === 0) return error.message;
  }
  return "Não foi possível salvar agora. Tente de novo em instantes.";
}
