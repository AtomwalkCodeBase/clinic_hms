/**
 * pages/doctor/PatientsPage.jsx
 * --------------------------------
 * Doctor's patient roster. Opens showing "My Patients" — everyone this
 * doctor has actually seen — instead of a blank search box, since that's
 * the doctor's own EHR/roster and the whole point of the page. Built from
 * the same visit-history endpoint the History page uses (already scoped to
 * this doctor's own patients server-side), deduped down to one row per
 * patient (most recent visit). Typing a search still searches every patient
 * at the hospital (via PATIENTS.SEARCH) for cases where the doctor needs to
 * look someone up who isn't in their own history yet.
 */
import { useState, useRef, useEffect, useMemo } from "react";
import { useNavigate }       from "react-router-dom";
import { AppShell }          from "../../components/layout/AppShell";
import { PageShell }         from "../../components/common/PageShell";
import DependentBadge        from "../../components/common/DependentBadge";
import apiClient             from "../../services/api.client";
import API_ENDPOINTS         from "../../config/api.config";
import { ROUTES }            from "../../config/routes.config";
import { Search, AlertTriangle, FolderOpen, SearchX, Filter, X } from "lucide-react";

function calcAge(dob) {
  if (!dob) return "—";
  const diff = Date.now() - new Date(dob).getTime();
  return Math.floor(diff / (365.25 * 24 * 3600 * 1000)) + "y";
}

export default function DoctorPatientsPage() {
  const navigate = useNavigate();
  const [query,        setQuery]        = useState("");
  const [results,      setResults]      = useState(null);
  const [totalMatches, setTotalMatches] = useState(0);
  const [truncated,    setTruncated]    = useState(false);
  const [networkMatch, setNetworkMatch] = useState(null);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState(null);
  const timerRef = useRef(null);

  // ── "My Patients" — loaded once on mount, shown whenever the search box
  // is empty. Deduped from this doctor's own visit history (most recent
  // visit per patient wins, since AppointmentHistoryView is already ordered
  // newest-first).
  const [myPatients, setMyPatients] = useState(null); // null = still loading
  const [myPatientsError, setMyPatientsError] = useState(false);

  useEffect(() => {
    apiClient.get(API_ENDPOINTS.OPD.HISTORY, { params: { page_size: 100 } })
      .then(({ data }) => {
        const seen = new Set();
        const roster = [];
        for (const visit of (data?.results || [])) {
          const key = visit.patient_uhid || visit.awpid;
          if (!key || seen.has(key)) continue;
          seen.add(key);
          roster.push(visit);
        }
        setMyPatients(roster);
      })
      .catch(() => { setMyPatients([]); setMyPatientsError(true); });
  }, []);

  function onQueryChange(val) {
    setQuery(val);
    clearTimeout(timerRef.current);
    if (val.trim().length < 2) { setResults(null); return; }
    timerRef.current = setTimeout(() => doSearch(val.trim()), 350);
  }

  async function doSearch(q) {
    setLoading(true);
    setError(null);
    try {
      const { data: envelope } = await apiClient.get(API_ENDPOINTS.PATIENTS.SEARCH, { params: { q } });
      const payload = envelope?.data || {};
      setResults(payload.results || []);
      setTotalMatches(payload.total_matches ?? (payload.results || []).length);
      setTruncated(!!payload.truncated);
      setNetworkMatch(payload.network_match || null);
    } catch (err) {
      setError("Search failed. Please try again.");
      setResults([]);
      setTotalMatches(0);
      setTruncated(false);
      setNetworkMatch(null);
    } finally {
      setLoading(false);
    }
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (query.trim().length >= 2) doSearch(query.trim());
  }

  // ── Filters — applied client-side over whichever list is showing (the
  // roster or a search result set). Last-visit range only makes sense for
  // the roster (search results don't carry a visit date), so it's hidden
  // once the doctor is actually searching.
  const [showFilters,     setShowFilters]     = useState(false);
  const [genderFilter,    setGenderFilter]    = useState("");
  const [dependentFilter, setDependentFilter] = useState(""); // "" | "dependent" | "adult"
  const [visitFrom,       setVisitFrom]       = useState("");
  const [visitTo,         setVisitTo]         = useState("");
  const hasActiveFilters = !!(genderFilter || dependentFilter || visitFrom || visitTo);

  function clearFilters() {
    setGenderFilter(""); setDependentFilter(""); setVisitFrom(""); setVisitTo("");
  }

  const filteredRoster = useMemo(() => {
    if (!myPatients) return myPatients;
    return myPatients.filter(p => {
      if (genderFilter && p.patient_gender !== genderFilter) return false;
      if (dependentFilter === "dependent" && !p.is_dependent) return false;
      if (dependentFilter === "adult" && p.is_dependent) return false;
      if (visitFrom && (!p.scheduled_date || p.scheduled_date < visitFrom)) return false;
      if (visitTo && (!p.scheduled_date || p.scheduled_date > visitTo)) return false;
      return true;
    });
  }, [myPatients, genderFilter, dependentFilter, visitFrom, visitTo]);

  const filteredResults = useMemo(() => {
    if (!results) return results;
    return results.filter(p => {
      if (genderFilter && p.gender !== genderFilter) return false;
      if (dependentFilter === "dependent" && !p.is_dependent) return false;
      if (dependentFilter === "adult" && p.is_dependent) return false;
      return true;
    });
  }, [results, genderFilter, dependentFilter]);

  function viewInHistory(uhid) {
    navigate(ROUTES.DOCTOR.HISTORY, { state: { patient: uhid } });
  }

  return (
    <AppShell>
      <PageShell title="Patient Search">

        {/* Search bar */}
        <form onSubmit={onSubmit}>
          <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 260px", position: "relative" }}>
              <span style={{
                position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)",
                display: "inline-flex", color: "var(--color-text-muted)", pointerEvents: "none",
              }}><Search size={16} /></span>
              <input
                type="text"
                value={query}
                onChange={e => onQueryChange(e.target.value)}
                placeholder="Search by name, UHID, or mobile number…"
                style={{
                  width: "100%", boxSizing: "border-box",
                  padding: "10px 14px 10px 38px",
                  border: "1.5px solid var(--color-border)",
                  borderRadius: 10, fontSize: 14, outline: "none",
                  color: "var(--color-text)", background: "#fff",
                }}
                onFocus={e => (e.target.style.borderColor = "var(--color-primary)")}
                onBlur={e => (e.target.style.borderColor = "var(--color-border)")}
                autoFocus
              />
            </div>
            <button type="submit" className="btn-primary" style={{ padding: "10px 24px" }}>
              Search
            </button>
            <button
              type="button"
              className={hasActiveFilters ? "btn-primary" : "btn-outline"}
              style={{ padding: "10px 20px", display: "flex", alignItems: "center", gap: 7, fontWeight: 700 }}
              onClick={() => setShowFilters(v => !v)}
            >
              <Filter size={14} /> Filters{hasActiveFilters ? " •" : ""}
            </button>
          </div>
        </form>

        {showFilters && (
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10,
            padding: 16, borderRadius: 12, marginBottom: 20,
            background: "var(--color-bg)", border: "1px solid var(--color-border)",
          }}>
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Gender</label>
              <select className="form-input" style={{ appearance: "auto" }} value={genderFilter} onChange={e => setGenderFilter(e.target.value)}>
                <option value="">Any</option>
                <option value="M">Male</option>
                <option value="F">Female</option>
                <option value="O">Other</option>
              </select>
            </div>
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Patient type</label>
              <select className="form-input" style={{ appearance: "auto" }} value={dependentFilter} onChange={e => setDependentFilter(e.target.value)}>
                <option value="">Any</option>
                <option value="dependent">Dependents only</option>
                <option value="adult">Adults only</option>
              </select>
            </div>
            {results === null && (
              <>
                <div>
                  <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Last visit from</label>
                  <input type="date" className="form-input" value={visitFrom} onChange={e => setVisitFrom(e.target.value)} />
                </div>
                <div>
                  <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Last visit to</label>
                  <input type="date" className="form-input" value={visitTo} onChange={e => setVisitTo(e.target.value)} />
                </div>
              </>
            )}
            {hasActiveFilters && (
              <div style={{ display: "flex", alignItems: "flex-end" }}>
                <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "8px 14px", display: "flex", alignItems: "center", gap: 5 }}
                  onClick={clearFilters}>
                  <X size={12} /> Clear
                </button>
              </div>
            )}
          </div>
        )}

        {/* Default state — this doctor's own patient roster, shown until they search */}
        {results === null && !loading && (
          myPatients === null ? (
            <div style={{ textAlign: "center", padding: 40, color: "var(--color-text-muted)" }}>Loading your patients…</div>
          ) : myPatientsError ? (
            <div style={{ textAlign: "center", padding: "48px 0" }}>
              <AlertTriangle size={32} style={{ color: "var(--color-text-muted)", marginBottom: 10 }} />
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Couldn't load your patients</div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Try searching above instead.</div>
            </div>
          ) : myPatients.length === 0 ? (
            <div style={{ textAlign: "center", padding: "48px 0" }}>
              <FolderOpen size={32} style={{ color: "var(--color-text-muted)", marginBottom: 10 }} />
              <div style={{ fontWeight: 600, marginBottom: 6 }}>No patients yet</div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Patients you've seen will show up here. Search above to find any patient at this hospital.
              </div>
            </div>
          ) : filteredRoster.length === 0 ? (
            <div style={{ textAlign: "center", padding: "48px 0" }}>
              <SearchX size={32} style={{ color: "var(--color-text-muted)", marginBottom: 10 }} />
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Nothing matches these filters</div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 12 }}>
                Try widening the gender, patient type, or visit date range.
              </div>
              <button className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }} onClick={clearFilters}>Clear filters</button>
            </div>
          ) : (
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{
                padding: "12px 20px", borderBottom: "1px solid var(--color-border)",
                fontSize: 13, color: "var(--color-text-muted)", display: "flex",
                justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 6,
              }}>
                <span>
                  My Patients — {filteredRoster.length}{hasActiveFilters ? ` of ${myPatients.length}` : ""} patient{filteredRoster.length !== 1 ? "s" : ""}
                </span>
                <span style={{ fontSize: 11 }}>Search above to find any patient at this hospital</span>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>UHID</th>
                    <th>Age / Gender</th>
                    <th>Last Visit</th>
                    <th>Chief Complaint</th>
                    <th style={{ width: 90 }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRoster.map(p => (
                    <tr key={p.awpid || p.patient_uhid}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          <div style={{ fontWeight: 700, fontSize: 13 }}>{p.patient_name || "—"}</div>
                          <DependentBadge patient={p} />
                        </div>
                        <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 1 }}>
                          {p.awpid || ""}
                        </div>
                      </td>
                      <td style={{ fontFamily: "monospace", fontSize: 12, color: "var(--color-primary)" }}>
                        {p.patient_uhid || "—"}
                      </td>
                      <td style={{ fontSize: 13 }}>
                        {p.patient_age != null ? `${p.patient_age}y` : "—"} / {
                          p.patient_gender === "M" ? "Male" :
                          p.patient_gender === "F" ? "Female" :
                          p.patient_gender || "—"
                        }
                      </td>
                      <td style={{ fontSize: 12 }}>{p.scheduled_date || "—"}</td>
                      <td style={{ fontSize: 12, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {p.chief_complaint || <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                      </td>
                      <td>
                        <button
                          className="btn-outline"
                          style={{ fontSize: 11, padding: "4px 12px" }}
                          onClick={() => viewInHistory(p.patient_uhid)}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}

        {loading && (
          <div style={{ textAlign: "center", padding: 40, color: "var(--color-text-muted)" }}>
            Searching…
          </div>
        )}

        {error && (
          <div style={{
            background: "#FEE2E2", color: "#991B1B", borderRadius: 8,
            padding: "12px 16px", fontSize: 13, marginBottom: 16,
          }}>{error}</div>
        )}

        {results !== null && !loading && (
          <>
            {results.length === 0 ? (
              networkMatch ? (
                <div style={{ textAlign: "center", padding: "48px 0" }}>
                  <SearchX size={32} style={{ color: "var(--color-text-muted)", marginBottom: 10 }} />
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>
                    Not registered at this hospital yet
                  </div>
                  <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 4 }}>
                    <strong style={{ color: "var(--color-text)" }}>{networkMatch.full_name}</strong> already
                    exists on the Atomwalk network, just not at this hospital.
                  </div>
                  <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                    Ask front desk to register them here — their shared history will carry over.
                  </div>
                </div>
              ) : (
                <div style={{ textAlign: "center", padding: "48px 0" }}>
                  <SearchX size={32} style={{ color: "var(--color-text-muted)", marginBottom: 10 }} />
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>No patients found</div>
                  <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                    Try a different name, UHID, or mobile number.
                  </div>
                </div>
              )
            ) : filteredResults.length === 0 ? (
              <div style={{ textAlign: "center", padding: "48px 0" }}>
                <SearchX size={32} style={{ color: "var(--color-text-muted)", marginBottom: 10 }} />
                <div style={{ fontWeight: 600, marginBottom: 6 }}>Nothing matches these filters</div>
                <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 12 }}>
                  {results.length} search result{results.length !== 1 ? "s" : ""}, but none match the gender/patient-type filter.
                </div>
                <button className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }} onClick={clearFilters}>Clear filters</button>
              </div>
            ) : (
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{
                  padding: "12px 20px", borderBottom: "1px solid var(--color-border)",
                  fontSize: 13, color: "var(--color-text-muted)",
                }}>
                  {truncated
                    ? `Showing first ${filteredResults.length} of ${totalMatches} matches — refine your search to narrow this down.`
                    : `${filteredResults.length}${hasActiveFilters ? ` of ${results.length}` : ""} result${filteredResults.length !== 1 ? "s" : ""} for "${query}"`}
                </div>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>UHID</th>
                      <th>Age / Gender</th>
                      <th>Blood Group</th>
                      <th>Mobile</th>
                      <th>Payer</th>
                      <th style={{ width: 90 }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredResults.map(p => (
                      <tr key={p.id}>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                            <div style={{ fontWeight: 700, fontSize: 13 }}>{p.full_name}</div>
                            <DependentBadge patient={p} />
                          </div>
                          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 1 }}>
                            {p.awpid || ""}
                          </div>
                        </td>
                        <td style={{ fontFamily: "monospace", fontSize: 12, color: "var(--color-primary)" }}>
                          {p.uhid || "—"}
                        </td>
                        <td style={{ fontSize: 13 }}>
                          {calcAge(p.date_of_birth)} / {
                            p.gender === "M" ? "Male" :
                            p.gender === "F" ? "Female" :
                            p.gender || "—"
                          }
                        </td>
                        <td>
                          {p.blood_group ? (
                            <span style={{
                              background: "#FEE2E2", color: "#DC2626",
                              padding: "2px 8px", borderRadius: 10,
                              fontSize: 11, fontWeight: 700,
                            }}>{p.blood_group}</span>
                          ) : <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                        </td>
                        <td style={{ fontSize: 12 }}>{p.mobile || "—"}</td>
                        <td style={{ fontSize: 12, textTransform: "capitalize" }}>
                          {p.payer_type || "self"}
                        </td>
                        <td>
                          <button
                            className="btn-outline"
                            style={{ fontSize: 11, padding: "4px 12px" }}
                            onClick={() => viewInHistory(p.uhid)}
                          >
                            View
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </PageShell>
    </AppShell>
  );
}
