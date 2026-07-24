"use client";

import { useEffect, useState } from "react";
import {
  getGradescopeStatus,
  saveGradescopeCredentials,
  deleteGradescopeCredentials,
  listGradescopeCourses,
  listGradescopeLinks,
  linkGradescopeCourse,
  unlinkGradescopeCourse,
  syncGradescopeCourse,
  type GradescopeStatus,
  type GradescopeCourse,
  type GradescopeLink,
  type GradescopeConnectInput,
} from "@/lib/api";

/**
 * frontend/src/components/settings/GradescopeConnect.tsx
 *
 * Two steps once connected:
 *   1. Connect credentials (password or pasted SSO session cookie)
 *   2. Link each Sapling course to a Gradescope course, then sync
 *
 * `userId` and the list of the user's Sapling courses (id + name) are
 * passed in as props since this component doesn't own that data —
 * wire it up from wherever your Settings/Gradebook page already has them
 * (e.g. from getCourses(userId) in api.ts).
 */
export function GradescopeConnect({
  userId,
  saplingCourses,
}: {
  userId: string;
  saplingCourses: { id: string; name: string }[];
}) {
  const [status, setStatus] = useState<GradescopeStatus | null>(null);
  const [authMode, setAuthMode] = useState<"password" | "cookies">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [gradescopeSession, setGradescopeSession] = useState("");
  const [signedToken, setSignedToken] = useState("");
  const [gsCourses, setGsCourses] = useState<GradescopeCourse[]>([]);
  const [links, setLinks] = useState<GradescopeLink[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  async function refreshAll() {
    const s = await getGradescopeStatus(userId);
    setStatus(s);
    if (s.has_credentials) {
      const [coursesRes, linksRes] = await Promise.all([
        listGradescopeCourses(userId),
        listGradescopeLinks(userId),
      ]);
      setGsCourses(coursesRes.courses);
      setLinks(linksRes.links);
    }
  }

  useEffect(() => {
    refreshAll().catch((e) => setError((e as Error).message));
  }, []);

  async function handleConnect() {
    setBusy(true);
    setError(null);
    try {
      const input: GradescopeConnectInput =
        authMode === "password"
          ? { auth_mode: "password", email, password }
          : {
              auth_mode: "cookies",
              gradescope_session: gradescopeSession,
              signed_token: signedToken || undefined,
            };
      await saveGradescopeCredentials(userId, input);
      setPassword("");
      setGradescopeSession("");
      setSignedToken("");
      await refreshAll();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    setBusy(true);
    setError(null);
    try {
      await deleteGradescopeCredentials(userId);
      setGsCourses([]);
      setLinks([]);
      await refreshAll();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleLinkChange(saplingCourseId: string, gradescopeCourseId: string) {
    setBusy(true);
    setError(null);
    try {
      if (!gradescopeCourseId) {
        await unlinkGradescopeCourse(userId, saplingCourseId);
      } else {
        await linkGradescopeCourse(userId, saplingCourseId, gradescopeCourseId);
      }
      const linksRes = await listGradescopeLinks(userId);
      setLinks(linksRes.links);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSync(saplingCourseId: string) {
    setBusy(true);
    setError(null);
    setSyncMessage(null);
    try {
      const result = await syncGradescopeCourse(userId, saplingCourseId);
      setSyncMessage(
        `Synced: ${result.inserted} new, ${result.updated} updated, ${result.skipped} unchanged` +
          (result.failed ? `, ${result.failed} failed` : "")
      );
      const linksRes = await listGradescopeLinks(userId);
      setLinks(linksRes.links);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (status?.has_credentials) {
    const linkByCourse = new Map(links.map((l) => [l.sapling_course_id, l]));

    return (
      <div className="rounded-lg border border-neutral-200 p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">Gradescope</h3>
          <button
            onClick={handleDisconnect}
            disabled={busy}
            className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Disconnect
          </button>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {syncMessage && <p className="text-sm text-green-700">{syncMessage}</p>}

        <div className="space-y-2">
          <p className="text-xs text-neutral-500">
            Link each course, then sync to pull in grades.
          </p>
          {saplingCourses.map((course) => {
            const link = linkByCourse.get(course.id);
            return (
              <div key={course.id} className="flex items-center gap-2 text-sm">
                <span className="w-40 truncate">{course.name}</span>
                <select
                  value={link?.gradescope_course_id ?? ""}
                  onChange={(e) => handleLinkChange(course.id, e.target.value)}
                  disabled={busy}
                  className="flex-1 rounded-md border border-neutral-300 px-2 py-1"
                >
                  <option value="">— not linked —</option>
                  {gsCourses.map((gc) => (
                    <option key={gc.id} value={gc.id}>
                      {gc.full_name || gc.name} ({gc.semester} {gc.year})
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => handleSync(course.id)}
                  disabled={busy || !link}
                  className="rounded-md bg-green-700 px-2 py-1 text-white disabled:opacity-40"
                >
                  Sync
                </button>
                {link?.last_synced_at && (
                  <span className="text-xs text-neutral-400 whitespace-nowrap">
                    {new Date(link.last_synced_at).toLocaleDateString()}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-neutral-200 p-4">
      <h3 className="font-semibold text-sm mb-1">Connect Gradescope</h3>
      <p className="text-sm text-neutral-600 mb-3">
        Connect once, then link courses below to sync grades automatically.
      </p>

      <div className="flex gap-4 mb-3 text-sm">
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            checked={authMode === "password"}
            onChange={() => setAuthMode("password")}
          />
          Gradescope login
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            checked={authMode === "cookies"}
            onChange={() => setAuthMode("cookies")}
          />
          SSO school (paste session cookie)
        </label>
      </div>

      {authMode === "password" ? (
        <div className="space-y-2 mb-3">
          <input
            type="email"
            placeholder="Gradescope email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm"
          />
          <input
            type="password"
            placeholder="Gradescope password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm"
          />
        </div>
      ) : (
        <div className="space-y-2 mb-3">
          <p className="text-xs text-neutral-500">
            Log into Gradescope normally in this browser, open DevTools → Application →
            Cookies → gradescope.com, and copy the <code>_gradescope_session</code> value
            below.
          </p>
          <input
            type="text"
            placeholder="_gradescope_session cookie value"
            value={gradescopeSession}
            onChange={(e) => setGradescopeSession(e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm font-mono"
          />
          <input
            type="text"
            placeholder="signed_token cookie value (optional)"
            value={signedToken}
            onChange={(e) => setSignedToken(e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm font-mono"
          />
        </div>
      )}

      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      <button
        onClick={handleConnect}
        disabled={busy}
        className="rounded-md bg-green-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
      >
        Connect
      </button>
    </div>
  );
}