// Helpers for the two dynamic routes, /manager/[id] and /store/[id].
// Pure functions only, so `node --test` can run them directly.

/**
 * With Cache Components on, a dynamic route must prerender at least one page or the build fails.
 * When there is no engine output there are no ids, so this one placeholder page is built instead;
 * it shows the "no engine run published" state.
 */
export const NO_RUN_PARAM = "none";

export function staticIds(ids: string[]): { id: string }[] {
  const unique = [...new Set(ids)];
  return unique.length > 0 ? unique.map((id) => ({ id })) : [{ id: NO_RUN_PARAM }];
}

/** The id from the URL, decoded if the router handed it over still percent-encoded. */
export function routeId(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}
