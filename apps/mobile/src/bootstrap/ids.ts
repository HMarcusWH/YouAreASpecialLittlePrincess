// Client intent identifiers (operation and request IDs). They make retries
// idempotent; they are not secrets, so a non-cryptographic source suffices.
let counter = 0;

export function newClientId(): string {
  counter = (counter + 1) % 1_679_616;
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}${counter.toString(36)}`;
}
