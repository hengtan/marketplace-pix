import { setupWorker } from "msw/browser";
import { enableMockPersistence } from "./db";
import { handlers } from "./handlers";

enableMockPersistence();
export const worker = setupWorker(...handlers);
