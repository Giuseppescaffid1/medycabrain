import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../contexts/AuthContext";
import { Button, fieldCls } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";
import { Wordmark } from "../components/layout/Sidebar";

export default function Login() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
    } catch {
      setError(t("login.error"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <PageTransition>
      <div className="flex min-h-dvh items-center justify-center bg-ground p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 text-center [&>div:first-child]:text-2xl">
            <Wordmark />
          </div>
          <form
            onSubmit={onSubmit}
            className="space-y-4 rounded-3xl border border-border bg-white p-6 shadow-float"
          >
            <div>
              <h1 className="text-lg font-bold text-heading">{t("login.title")}</h1>
              <p className="text-sm text-muted">{t("login.subtitle")}</p>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-navy">
                {t("login.username")}
              </label>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                className={fieldCls + " w-full bg-ground"}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-navy">
                {t("login.password")}
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className={fieldCls + " w-full bg-ground"}
              />
            </div>
            {error && (
              <div className="text-sm font-semibold text-danger">⚠ {error}</div>
            )}
            <Button type="submit" loading={loading} className="w-full">
              {t("login.submit")}
            </Button>
          </form>
        </div>
      </div>
    </PageTransition>
  );
}
