import { apiClient } from "./client";
import type {
  Account,
  Cluster,
  ClusterArgument,
  Paginated,
  ReelDetail,
  ReelListItem,
  Stats,
  Tag,
} from "./types";

export type Scope = "medyca" | "competitor";

// ── Reels ──────────────────────────────────────────────────────────────
export interface ReelFilters {
  search?: string;
  scope?: Scope;
  account?: number;
  cluster?: number;
  tag?: number;
  content_format?: string;
  favorite?: boolean;
  inspiration?: boolean;
  ordering?: string;
  /** ISO date-time bounds on posted_at (the Timeline asks one month at a time). */
  posted_after?: string;
  posted_before?: string;
  page?: number;
  page_size?: number;
  excluded?: boolean;
}

export async function fetchReels(filters: ReelFilters): Promise<Paginated<ReelListItem>> {
  const params: Record<string, unknown> = {};
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== "" && v !== false) params[k] = v;
  });
  const { data } = await apiClient.get<Paginated<ReelListItem>>("/reels/", { params });
  return data;
}

export async function fetchReel(id: number): Promise<ReelDetail> {
  const { data } = await apiClient.get<ReelDetail>(`/reels/${id}/`);
  return data;
}

export async function patchAnnotation(
  id: number,
  payload: Partial<{ is_favorite: boolean; is_inspiration: boolean; note: string }>
) {
  const { data } = await apiClient.patch(`/reels/${id}/annotation/`, payload);
  return data;
}

export async function addTag(reelId: number, body: { tag_id?: number; name?: string }) {
  const { data } = await apiClient.post(`/reels/${reelId}/tags/`, body);
  return data;
}

export async function removeTag(reelId: number, tagId: number) {
  const { data } = await apiClient.delete(`/reels/${reelId}/tags/${tagId}/`);
  return data;
}

// ── Accounts ───────────────────────────────────────────────────────────
/**
 * Every row of a paginated list, following `next`. The API pages at 24, and
 * reading only the first page silently dropped accounts 25 and 26 from the
 * list. Capped at 50 pages so a broken `next` cannot loop forever.
 */
export async function fetchAllPages<T>(
  url: string,
  params: Record<string, unknown> = {}
): Promise<T[]> {
  const out: T[] = [];
  let page = 1;
  for (let i = 0; i < 50; i++) {
    const { data } = await apiClient.get<T[] | Paginated<T>>(url, {
      params: { ...params, page_size: 100, page },
    });
    if (Array.isArray(data)) return data;
    out.push(...data.results);
    if (!data.next) break;
    page += 1;
  }
  return out;
}

// No parameters on purpose: react-query hands its context object to a bare
// `queryFn: fetchAccounts`, which a `removed` flag would read as true.
export async function fetchAccounts(): Promise<Account[]> {
  return fetchAllPages<Account>("/accounts/");
}

/** Only the accounts the client removed — the "Rimossi" filter. */
export async function fetchRemovedAccounts(): Promise<Account[]> {
  return fetchAllPages<Account>("/accounts/", { removed: 1 });
}

export async function restoreAccount(id: number): Promise<Account> {
  const { data } = await apiClient.post<Account>(`/accounts/${id}/restore/`);
  return data;
}

export type AddAccountResult = Account & {
  /** True when an account the client had removed was brought back instead. */
  restored?: boolean;
  /** Set when the Apify budget is spent: when collection resumes. */
  collection_paused_until?: string | null;
};

export async function addAccount(
  username: string,
  ownerType: Account["owner_type"] = "competitor"
): Promise<AddAccountResult> {
  const { data } = await apiClient.post<AddAccountResult>("/accounts/", {
    username,
    owner_type: ownerType,
  });
  return data;
}

export async function updateAccount(id: number, payload: Partial<Account>): Promise<Account> {
  const { data } = await apiClient.patch<Account>(`/accounts/${id}/`, payload);
  return data;
}

export async function deleteAccount(id: number): Promise<void> {
  await apiClient.delete(`/accounts/${id}/`);
}

// ── Clusters ───────────────────────────────────────────────────────────
export async function fetchClusters(scope: Scope = "competitor"): Promise<Cluster[]> {
  const { data } = await apiClient.get<Cluster[]>("/clusters/", { params: { scope } });
  return data;
}

export async function fetchCluster(id: number): Promise<Cluster> {
  const { data } = await apiClient.get<Cluster>(`/clusters/${id}/`);
  return data;
}

export async function fetchClusterArguments(id: number): Promise<ClusterArgument[]> {
  const { data } = await apiClient.get<ClusterArgument[]>(`/clusters/${id}/arguments/`);
  return data;
}

// ── Tags ───────────────────────────────────────────────────────────────
export async function fetchTags(): Promise<Tag[]> {
  const { data } = await apiClient.get<Tag[]>("/tags/");
  return data;
}

// ── Stats ──────────────────────────────────────────────────────────────
export async function fetchStats(): Promise<Stats> {
  const { data } = await apiClient.get<Stats>("/stats/overview/");
  return data;
}

// ── Esclusione contenuti (video di auguri, ospiti fuori tema…) ─────────
export async function excludeReel(id: number): Promise<void> {
  await apiClient.post(`/reels/${id}/exclude/`);
}

export async function restoreReel(id: number): Promise<void> {
  await apiClient.post(`/reels/${id}/restore/`);
}
