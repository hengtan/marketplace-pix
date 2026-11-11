import * as z from "zod/mini";

export const loginSchema = z.object({
  email: z.email("Informe um e-mail válido"),
  password: z.string().check(z.minLength(1, "Informe sua senha")),
});
export type LoginForm = z.infer<typeof loginSchema>;

export const registerSchema = z.object({
  name: z.string().check(z.trim(), z.minLength(2, "Informe seu nome completo")),
  email: z.email("Informe um e-mail válido"),
  password: z
    .string()
    .check(
      z.minLength(8, "Use 8 caracteres ou mais"),
      z.regex(/\d/, "Inclua pelo menos um número"),
    ),
});
export type RegisterForm = z.infer<typeof registerSchema>;

export function passwordScore(pw: string): number {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/\d/.test(pw) && /[a-zA-Z]/.test(pw)) score++;
  if (/[^a-zA-Z0-9]/.test(pw) && pw.length >= 8) score++;
  return score;
}

export function safeRedirect(value: string | undefined): string {
  if (value?.startsWith("/") && !value.startsWith("//")) return value;
  return "/";
}
