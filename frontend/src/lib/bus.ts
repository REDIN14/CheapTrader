// A tiny announcement board: things the server pushes over the live stream that are not prices
// (a drawing was added by a script) are posted here, and whoever cares listens.

export type Notice = { type: string; [key: string]: unknown };

const listeners = new Set<(notice: Notice) => void>();

export function postNotice(notice: Notice): void {
  for (const listener of listeners) listener(notice);
}

/** Listen for notices; returns the function that stops listening. */
export function onNotice(listener: (notice: Notice) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
