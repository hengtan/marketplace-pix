import * as z from "zod/mini";

export const citationSchema = z.object({
  product_id: z.string(),
  slug: z.string(),
  name: z.string(),
  score: z.catch(z.number(), 0),
});
export type Citation = z.infer<typeof citationSchema>;

export const toolCallSchema = z.object({
  name: z.string(),
  arguments: z.catch(z.record(z.string(), z.unknown()), {}),
  result_summary: z.catch(z.string(), ""),
  duration_ms: z.catch(z.number(), 0),
});
export type ToolCall = z.infer<typeof toolCallSchema>;

export const retrievedSchema = z.object({
  chunk_id: z.string(),
  product_id: z.string(),
  slug: z.string(),
  name: z.string(),
  category: z.catch(z.string(), ""),
  price_cents: z.catch(z.number(), 0),
  content: z.catch(z.string(), ""),
  score: z.catch(z.number(), 0),
  source: z.catch(z.string(), ""),
});
export type Retrieved = z.infer<typeof retrievedSchema>;

export const chatResponseSchema = z.object({
  session_id: z.string(),
  answer: z.string(),
  citations: z.catch(z.array(citationSchema), []),
  tool_calls: z.catch(z.array(toolCallSchema), []),
  retrieved: z.catch(z.array(retrievedSchema), []),
  latency_ms: z.catch(z.number(), 0),
  cached: z.optional(z.boolean()),
  degraded: z.optional(z.boolean()),
  warning: z.pipe(
    z.nullish(z.string()),
    z.transform((value) => value ?? undefined),
  ),
});
export type ChatResponse = z.infer<typeof chatResponseSchema>;

export const sessionSchema = z.object({
  session_id: z.string(),
  created_at: z.optional(z.string()),
  messages: z.array(
    z.object({
      role: z.string(),
      content: z.string(),
      created_at: z.optional(z.string()),
      citations: z.catch(z.array(citationSchema), []),
      tool_calls: z.catch(z.array(toolCallSchema), []),
    }),
  ),
});
export type SessionResponse = z.infer<typeof sessionSchema>;

export type AssistantEvent =
  | { type: "tool_call"; call: ToolCall }
  | { type: "token"; text: string }
  | { type: "done"; result: ChatResponse }
  | { type: "warning"; detail: string; reason: string }
  | { type: "error"; detail: string; scope?: string; limit?: string; retryAfter?: number };
