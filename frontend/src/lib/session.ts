type ExpiredHandler = () => void;

let onExpired: ExpiredHandler | null = null;

export function setSessionExpiredHandler(handler: ExpiredHandler | null) {
  onExpired = handler;
}

export function notifySessionExpired() {
  onExpired?.();
}
