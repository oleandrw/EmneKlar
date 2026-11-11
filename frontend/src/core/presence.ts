/**
 * Tells EmneKlar that this window is open, for as long as it is: one connection to `/api/system/presence` that
 * stays open. When the last EmneKlar window has been closed, the program stops by itself after a short wait
 * (backend `core/presence.py`). Returns the function that closes the connection.
 */
export function announceWindow(): () => void {
  if (typeof EventSource === "undefined") return () => {};
  const source = new EventSource("/api/system/presence");
  return () => source.close();
}
