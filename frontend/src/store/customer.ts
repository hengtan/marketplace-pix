import { uuid } from "@/lib/uuid";

const ID_KEY = "praca-customer-id";
const CONTACT_KEY = "praca-contact";
const ATTEMPT_KEY = "praca-checkout-attempt";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

export function getCustomerId(): string {
  const existing = read(ID_KEY);
  if (existing) return existing;
  const id = uuid();
  write(ID_KEY, id);
  return id;
}

export interface Contact {
  name: string;
  email: string;
}

export function getContact(): Contact {
  try {
    const raw = read(CONTACT_KEY);
    if (raw) return JSON.parse(raw) as Contact;
  } catch {
    /* ignore */
  }
  return { name: "", email: "" };
}

export function saveContact(contact: Contact) {
  write(CONTACT_KEY, JSON.stringify(contact));
}

interface Attempt {
  key: string;
  signature: string;
}

export function signatureOf(items: { product_id: string; quantity: number }[], contact: Contact) {
  const parts = [...items]
    .sort((a, b) => a.product_id.localeCompare(b.product_id))
    .map((i) => `${i.product_id}:${i.quantity}`);
  return `${parts.join("|")}#${contact.email.trim().toLowerCase()}`;
}

export function getIdempotencyKey(signature: string): string {
  try {
    const raw = read(ATTEMPT_KEY);
    if (raw) {
      const attempt = JSON.parse(raw) as Attempt;
      if (attempt.signature === signature) return attempt.key;
    }
  } catch {
    /* ignore */
  }
  const key = uuid();
  write(ATTEMPT_KEY, JSON.stringify({ key, signature } satisfies Attempt));
  return key;
}

export function clearIdempotencyKey() {
  try {
    localStorage.removeItem(ATTEMPT_KEY);
  } catch {
    /* ignore */
  }
}
