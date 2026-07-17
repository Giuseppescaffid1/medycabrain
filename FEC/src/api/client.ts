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
