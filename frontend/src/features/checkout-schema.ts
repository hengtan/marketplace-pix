import * as z from "zod/mini";

export const contactSchema = z.object({
  name: z.string().check(
    z.trim(),
    z.minLength(2, "Informe seu nome completo"),
    z.refine((v) => v.split(/\s+/).length >= 2, "Informe nome e sobrenome"),
  ),
  email: z.pipe(
    z.string().check(z.trim(), z.minLength(1, "Informe seu e-mail")),
    z.email("Esse e-mail não parece válido"),
  ),
});

export type ContactForm = z.infer<typeof contactSchema>;
