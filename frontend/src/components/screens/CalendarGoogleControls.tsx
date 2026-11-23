import { Icon } from "../Icon";

export function GoogleCalendarActions({
  connected, eventsEnabled, exporting, updating, importing, calendarUnavailable,
  onConnect, onExport, onRefresh, onToggle,
}: {
  connected: boolean;
  eventsEnabled: boolean;
  exporting: boolean;
  updating: boolean;
  importing: boolean;
  calendarUnavailable: boolean;
  onConnect: () => void;
  onExport: () => void;
  onRefresh: () => void;
  onToggle: () => void;
}) {
  return (
    <>
      {connected ? (
        <>
          <button data-testid="calendar-export-all-google" className="btn btn--sm" onClick={onExport} disabled={exporting || updating || calendarUnavailable}>
            <Icon name="send" size={12} /> {exporting ? "Exporting…" : "Export all to Google"}
          </button>
          {eventsEnabled && <button data-testid="calendar-refresh-google" className="btn btn--sm" onClick={onRefresh} disabled={importing || updating}>
            <Icon name="cal" size={12} /> {importing ? "Loading…" : "Refresh Google events"}
          </button>}
          <button
            data-testid="calendar-toggle-google-events"
            className="btn btn--sm"
            onClick={onToggle}
            disabled={exporting || updating}
          >
            {updating ? "Updating…" : eventsEnabled ? "Disconnect events" : "Reconnect events"}
          </button>
        </>
      ) : (
        <button data-testid="calendar-connect-google" className="btn btn--sm btn--primary" onClick={onConnect}>
          <Icon name="cal" size={12} /> Connect Google
        </button>
      )}
    </>
  );
}

export function GoogleCalendarStatus({
  connected, eventsEnabled, importing, error, eventCount, isYearView, onConnect, onRefresh,
}: {
  connected: boolean;
  eventsEnabled: boolean;
  importing: boolean;
  error: string | null;
  eventCount: number;
  isYearView: boolean;
  onConnect: () => void;
  onRefresh: () => void;
}) {
  if (!connected) return null;
  return (
    <>
      <p style={{ margin: "12px 32px 0", fontSize: 12, color: "var(--text-muted)" }}>
          {eventsEnabled ? "Google events appear automatically for the dates you’re viewing. Refresh to fetch changes." : "Google events are hidden. Your Google account remains connected."} Google exports add dated assignments once. Later edits and deletions in Sapling won’t update Google events. Undated and already exported assignments are skipped.
      </p>

      {eventsEnabled && (
        <div style={{ margin: "8px 32px", fontSize: 12 }} aria-live="polite">
          {importing ? "Loading Google events…" : error
            ? <span role="alert">{error} <button data-testid="calendar-retry-google" className="btn btn--sm" onClick={onRefresh}>Retry Google events</button> <button data-testid="calendar-reauthorize-google" className="btn btn--sm" onClick={onConnect}>Reauthorize Google</button></span>
            : `${eventCount} Google event${eventCount === 1 ? "" : "s"} linked for this ${isYearView ? "year" : "view"}.`}
        </div>
      )}
    </>
  );
}
