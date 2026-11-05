import axios from "axios";

const TOKEN_KEY = "brain_token";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "/api/v1",
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Token ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem("brain_user");
      window.dispatchEvent(new Event("brain:auth-cleared"));
    }
    return Promise.reject(error);
  }
);

export { TOKEN_KEY };

/** Status of a failed request, or undefined when the server never answered. */
export function errorStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined;
}

/**
 * A flat list that the interface treats as a whole (ideas, drafts): follows
 * the paginator's `next` instead of silently stopping at the first page.
 * Capped, so a runaway list cannot loop for ever.
 */
export async function fetchAllPages<T>(
  url: string,
  params: Record<string, unknown> = {},
  maxPages = 10
): Promise<T[]> {
  const out: T[] = [];
  for (let page = 1; page <= maxPages; page++) {
    const { data } = await apiClient.get<T[] | { results: T[]; next: string | null }>(url, {
      params: { ...params, page, page_size: 200 },
    });
    if (Array.isArray(data)) return data;
    out.push(...data.results);
    if (!data.next) break;
  }
  return out;
}
