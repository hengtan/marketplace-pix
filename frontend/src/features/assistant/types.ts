import { z } from "zod";

export const citationSchema = z.object({
  product_id: z.string(),
  slug: z.string(),
  name: z.string(),
  score: z.number().catch(0),
});
export type Citation = z.infer<typeof citationSchema>;

export const toolCallSchema = z.object({
  name: z.string(),
  arguments: z.record(z.string(), z.unknown()).catch({}),
  result_summary: z.string().catch(""),
  duration_ms: z.number().catch(0),
});
export type ToolCall = z.infer<typeof toolCallSchema>;

export const retrievedSchema = z.object({
  chunk_id: z.string(),
  product_id: z.string(),
  slug: z.string(),
  name: z.string(),
  category: z.string().catch(""),
  price_cents: z.number().catch(0),
  content: z.string().catch(""),
  score: z.number().catch(0),
  source: z.string().catch(""),
});
export type Retrieved = z.infer<typeof retrievedSchema>;

export const chatResponseSchema = z.object({
  session_id: z.string(),
  answer: z.string(),
  citations: z.array(citationSchema).catch([]),
  tool_calls: z.array(toolCallSchema).catch([]),
  retrieved: z.array(retrievedSchema).catch([]),
  latency_ms: z.number().catch(0),
});
export type ChatResponse = z.infer<typeof chatResponseSchema>;

export const sessionSchema = z.object({
  session_id: z.string(),
  created_at: z.string().optional(),
  messages: z.array(
    z.object({
      role: z.string(),
      content: z.string(),
      created_at: z.string().optional(),
      citations: z.array(citationSchema).catch([]),
      tool_calls: z.array(toolCallSchema).catch([]),
    }),
  ),
});
export type SessionResponse = z.infer<typeof sessionSchema>;

export type AssistantEvent =
  | { type: "tool_call"; call: ToolCall }
  | { type: "token"; text: string }
  | { type: "done"; result: ChatResponse }
  | { type: "error"; detail: string };
