import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { fetchAccounts } from "../api/endpoints";
import { fetchBlogSources } from "../api/blogSources";
import { listUploads } from "../api/uploads";
import { PageTransition } from "../components/ui/motion";
import { Tabs } from "../components/manage/parts";
import { AccountsPanel } from "../components/sources/AccountsPanel";
import { BlogSourcesPanel } from "../components/sources/BlogSourcesPanel";
import { UploadPanel } from "../components/uploads/UploadPanel";

/**
 * Everything you manage, in one place: Instagram profiles, blogs, uploaded
 * interviews.
 *
 * They used to be three long sections stacked on one scroll, so reaching the
 * uploads meant scrolling past every account and every blog. They are tabs
 * now: one list on screen at a time, the page header and the tabs stay put,
 * only the list scrolls. The open tab lives in the URL (`?tab=blogs`) so a
 * reload, a back button or a shared link all land on the same list.
 *
 * The counts on the tabs come from the same react-query keys the panels use,
 * so they cost no extra request and cannot disagree with the tables.
 */
const TAB_IDS = ["instagram", "blogs", "uploads"] as const;
type TabId = (typeof TAB_IDS)[number];

export default function Accounts() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();

  const raw = params.get("tab") as TabId | null;
  const tab: TabId = raw && TAB_IDS.includes(raw) ? raw : "instagram";
  const setTab = (id: string) => setParams({ tab: id }, { replace: true });

  const accounts = useQuery({ queryKey: ["accounts"], queryFn: fetchAccounts });
  const blogs = useQuery({ queryKey: ["blog-sources"], queryFn: fetchBlogSources });
  const uploads = useQuery({ queryKey: ["uploads"], queryFn: listUploads });

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-4 pt-4 sm:px-6">
          <h1 className="text-xl font-bold text-heading">{t("manage.title")}</h1>
          <p className="mt-1 max-w-[70ch] text-sm text-muted">{t("manage.subtitle")}</p>
          <div className="mt-4">
            <Tabs
              value={tab}
              onChange={setTab}
              items={[
                {
                  id: "instagram",
                  label: t("manage.tabInstagram"),
                  count: accounts.data?.length,
                },
                { id: "blogs", label: t("manage.tabBlogs"), count: blogs.data?.length },
                { id: "uploads", label: t("manage.tabUploads"), count: uploads.data?.length },
              ]}
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          {tab === "instagram" && <AccountsPanel />}
          {tab === "blogs" && <BlogSourcesPanel />}
          {tab === "uploads" && <UploadPanel />}
        </div>
      </div>
    </PageTransition>
  );
}
