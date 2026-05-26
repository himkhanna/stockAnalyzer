import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Dashboard } from "./pages/Dashboard";
import { InsightsPage } from "./pages/Insights";
import { LookupPage } from "./pages/Lookup";
import { PortfolioPage } from "./pages/Portfolio";
import { TopBar, type TabKey } from "./components/TopBar";
import { api } from "./api";

export default function App() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<TabKey>("dashboard");
  const [loadedAt, setLoadedAt] = useState<string | undefined>(undefined);
  const [refreshing, setRefreshing] = useState(false);

  async function refresh() {
    setRefreshing(true);
    try {
      const data = await api.refreshDashboard();
      qc.setQueryData(["dashboard"], data);
      setLoadedAt(data.loaded_at);
      qc.invalidateQueries({ queryKey: ["holdings"] });
    } catch (e) {
      console.error(e);
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="min-h-full">
      <TopBar
        tab={tab}
        onTab={setTab}
        loadedAt={loadedAt}
        onRefresh={refresh}
        refreshing={refreshing}
      />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {tab === "dashboard" && <Dashboard onLoadedAt={setLoadedAt} />}
        {tab === "insights" && <InsightsPage />}
        {tab === "lookup" && <LookupPage />}
        {tab === "portfolio" && <PortfolioPage />}
      </main>
    </div>
  );
}
