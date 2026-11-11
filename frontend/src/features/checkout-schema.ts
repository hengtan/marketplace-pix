import { z } from "zod";

export const contactSchema = z.object({
  name: z
    .string()
    .trim()
    .min(2, "Informe seu nome completo")
    .refine((v) => v.split(/\s+/).length >= 2, "Informe nome e sobrenome"),
  email: z
    .string()
    .trim()
    .min(1, "Informe seu e-mail")
    .pipe(z.email("Esse e-mail não parece válido")),
});

export type ContactForm = z.infer<typeof contactSchema>;
