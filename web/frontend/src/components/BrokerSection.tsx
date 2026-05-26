import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  Link2Off,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import type { SyncPreview } from "../types";

interface Props {
  onSynced: () => void;
}

export function BrokerSection({ onSynced }: Props) {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["icici-status"],
    queryFn: api.iciciStatus,
    refetchOnWindowFocus: false,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["icici-status"] });

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-bold">ICICI Direct sync</h2>
        <span className="text-xs text-zinc-500">
          Read-only · holdings only · no orders ever
        </span>
      </div>

      <div className="card p-4 space-y-4">
        {status.isLoading && (
          <div className="text-sm text-zinc-500">Loading…</div>
        )}

        {status.data && (
          <>
            <StatusLine
              hasCreds={status.data.has_credentials}
              connected={status.data.connected}
              expiresAt={status.data.session_expires_at}
            />

            {!status.data.has_credentials && (
              <CredentialsForm onSaved={refresh} />
            )}

            {status.data.has_credentials && !status.data.connected && (
              <SessionForm
                loginUrl={status.data.login_url}
                onConnected={refresh}
              />
            )}

            {status.data.has_credentials && status.data.connected && (
              <SyncBlock onApplied={onSynced} />
            )}

            {status.data.has_credentials && (
              <button
                className="btn-ghost text-xs text-bear-500"
                onClick={async () => {
                  if (!confirm("Disconnect and clear stored credentials?")) return;
                  await api.iciciDisconnect();
                  refresh();
                }}
              >
                <Link2Off size={14} />
                Disconnect & clear credentials
              </button>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function StatusLine({
  hasCreds,
  connected,
  expiresAt,
}: {
  hasCreds: boolean;
  connected: boolean;
  expiresAt: string | null;
}) {
  if (!hasCreds) {
    return (
      <div className="flex items-center gap-2 text-sm text-zinc-500">
        <AlertCircle size={16} />
        Not configured. Add your Breeze API key and secret to begin.
      </div>
    );
  }
  if (!connected) {
    return (
      <div className="flex items-center gap-2 text-sm text-amber-600 dark:text-amber-400">
        <AlertCircle size={16} />
        Credentials saved, but no active session. Generate a session token to connect.
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 text-sm text-bull-500">
      <CheckCircle2 size={16} />
      Connected · session expires {expiresAt ? formatExpiry(expiresAt) : "(midnight IST)"}
    </div>
  );
}

function formatExpiry(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function CredentialsForm({ onSaved }: { onSaved: () => void }) {
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const m = useMutation({
    mutationFn: () => api.iciciSetCredentials(key.trim(), secret.trim()),
    onSuccess: () => {
      setSecret("");
      onSaved();
    },
  });
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (key.trim() && secret.trim()) m.mutate();
      }}
    >
      <p className="text-xs text-zinc-500 leading-relaxed">
        Get an API key + secret from{" "}
        <a
          href="https://api.icicidirect.com/apiuser/home"
          target="_blank"
          rel="noreferrer"
          className="underline"
        >
          ICICI Direct's developer portal
        </a>
        . They're stored locally in your SQLite database and are never sent
        anywhere except to Breeze.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">API key</label>
          <input
            className="input font-mono"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">API secret</label>
          <input
            className="input font-mono"
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            autoComplete="off"
          />
        </div>
      </div>
      <button
        className="btn-primary"
        type="submit"
        disabled={!key.trim() || !secret.trim() || m.isPending}
      >
        {m.isPending ? "Saving…" : "Save credentials"}
      </button>
      {m.error && (
        <div className="text-sm text-bear-500">{(m.error as Error).message}</div>
      )}
    </form>
  );
}

function SessionForm({
  loginUrl,
  onConnected,
}: {
  loginUrl: string | null;
  onConnected: () => void;
}) {
  const [token, setToken] = useState("");
  const m = useMutation({
    mutationFn: () => api.iciciSetSession(token.trim()),
    onSuccess: () => {
      setToken("");
      onConnected();
    },
  });

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (token.trim()) m.mutate();
      }}
    >
      <ol className="text-xs text-zinc-500 leading-relaxed list-decimal pl-5 space-y-1">
        <li>
          Open the ICICI login page below — sign in with your Direct
          credentials.
        </li>
        <li>
          After login, you'll be redirected. Copy the <code>apisession</code>
          {" "}query-string value from the redirected URL.
        </li>
        <li>Paste it into the field below.</li>
        <li>
          Sessions expire at midnight IST — repeat this once per trading day.
        </li>
      </ol>
      {loginUrl && (
        <a
          href={loginUrl}
          target="_blank"
          rel="noreferrer"
          className="btn-ghost text-xs"
        >
          <ExternalLink size={14} />
          Open ICICI login
        </a>
      )}
      <div>
        <label className="text-xs text-zinc-500 mb-1 block">
          Session token (apisession value)
        </label>
        <input
          className="input font-mono"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoComplete="off"
        />
      </div>
      <button
        className="btn-primary"
        type="submit"
        disabled={!token.trim() || m.isPending}
      >
        {m.isPending ? "Connecting…" : "Connect"}
      </button>
      {m.error && (
        <div className="text-sm text-bear-500">{(m.error as Error).message}</div>
      )}
    </form>
  );
}

function SyncBlock({ onApplied }: { onApplied: () => void }) {
  const [preview, setPreview] = useState<SyncPreview | null>(null);
  const previewM = useMutation({
    mutationFn: () => api.iciciSyncPreview(),
    onSuccess: setPreview,
  });
  const applyM = useMutation({
    mutationFn: () => api.iciciSyncApply(),
    onSuccess: () => {
      setPreview(null);
      onApplied();
    },
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button
          className="btn-ghost text-xs"
          onClick={() => previewM.mutate()}
          disabled={previewM.isPending}
        >
          {previewM.isPending ? (
            <>
              <Loader2 size={14} className="animate-spin" /> Fetching…
            </>
          ) : (
            <>
              <RefreshCw size={14} /> Fetch holdings (preview)
            </>
          )}
        </button>
        {preview && (
          <span className="text-xs text-zinc-500">
            {preview.add_count} new · {preview.update_count} updated ·{" "}
            {preview.unchanged_count} unchanged · {preview.unresolved_count} unresolved
          </span>
        )}
      </div>
      {previewM.error && (
        <div className="text-sm text-bear-500">
          {(previewM.error as Error).message}
        </div>
      )}

      {preview && preview.rows.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-md border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-50 dark:bg-zinc-900 text-zinc-500 text-xs uppercase tracking-wider">
                <tr>
                  <th className="text-left px-3 py-2">Action</th>
                  <th className="text-left px-3 py-2">Resolved</th>
                  <th className="text-left px-3 py-2">Broker code</th>
                  <th className="text-left px-3 py-2">ISIN</th>
                  <th className="text-right px-3 py-2">Qty</th>
                  <th className="text-right px-3 py-2">Avg cost</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r, i) => (
                  <tr
                    key={`${r.isin}-${i}`}
                    className="border-t border-zinc-200 dark:border-zinc-800"
                  >
                    <td className="px-3 py-2">
                      <ActionPill action={r.action} />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {r.resolved_ticker ? (
                        <>
                          {r.resolved_ticker}
                          <span className="text-zinc-400 ml-1">
                            .{r.resolved_market}
                          </span>
                        </>
                      ) : (
                        <span className="text-bear-500">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {r.broker_stock_code}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-zinc-500">
                      {r.isin}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {r.quantity}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {r.average_price.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.unresolved_count > 0 && (
            <div className="text-xs text-amber-600 dark:text-amber-400">
              {preview.unresolved_count} row{preview.unresolved_count !== 1 && "s"}{" "}
              couldn't be mapped to an NSE ticker. Add their ISINs to{" "}
              <code>.ticker_overrides.json</code> in the project root.
            </div>
          )}
          <button
            className="btn-primary"
            onClick={() => applyM.mutate()}
            disabled={
              applyM.isPending ||
              preview.add_count + preview.update_count === 0
            }
          >
            {applyM.isPending
              ? "Applying…"
              : `Apply ${preview.add_count + preview.update_count} change${
                  preview.add_count + preview.update_count === 1 ? "" : "s"
                }`}
          </button>
          {applyM.data && (
            <div className="text-sm text-bull-500">
              Synced {applyM.data.upserted} holding
              {applyM.data.upserted === 1 ? "" : "s"}.
            </div>
          )}
          {applyM.error && (
            <div className="text-sm text-bear-500">
              {(applyM.error as Error).message}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ActionPill({
  action,
}: {
  action: "add" | "update" | "unchanged" | "unresolved";
}) {
  const styles = {
    add: "bg-bull-50 text-bull-600 dark:bg-bull-900/30 dark:text-bull-500",
    update: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
    unchanged: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
    unresolved: "bg-bear-50 text-bear-600 dark:bg-bear-900/30 dark:text-bear-500",
  } as const;
  return (
    <span className={`text-[11px] font-semibold px-2 py-0.5 rounded uppercase tracking-wider ${styles[action]}`}>
      {action}
    </span>
  );
}
