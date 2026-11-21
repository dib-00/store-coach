/** Every figure in the file is a check: an object with id, kind, params, value and display. */
export function countChecks(node: unknown): number {
  if (Array.isArray(node)) return node.reduce((n: number, x) => n + countChecks(x), 0);
  if (node && typeof node === "object") {
    const o = node as Record<string, unknown>;
    const self = ["id", "kind", "params", "value", "display"].every((k) => k in o) ? 1 : 0;
    return self + Object.values(o).reduce((n: number, x) => n + countChecks(x), 0);
  }
  return 0;
}
