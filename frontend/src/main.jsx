import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  LayoutDashboard,
  ReceiptText,
  Users,
  BookOpen,
  LogOut,
  Plus,
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  RefreshCw,
  ShieldCheck,
  Upload,
  Trash2,
} from "lucide-react";
import { api, post, downloadJSON, downloadReceipt } from "./api";
import "./style.css";
const display = (s) =>
  String(s || "")
    .replaceAll("_", " ")
    .toLowerCase();
const money = (amount, currency) => `${currency || ""} ${amount ?? "—"}`;
const date = (s) => (s ? new Date(s).toLocaleString() : "");
function Badge({ value }) {
  return (
    <span className={`badge ${value?.toLowerCase()}`}>{display(value)}</span>
  );
}
function Field({ label, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
function Empty({
  title = "Nothing here yet",
  text = "Your reports will appear here.",
}) {
  return (
    <div className="empty">
      <ReceiptText size={38} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
function App() {
  const [user, setUser] = useState(null),
    [checking, setChecking] = useState(true),
    [page, setPage] = useState("overview"),
    [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  useEffect(() => {
    let live = true;
    const expired = () => {
      setUser(null);
      setPage("overview");
    };
    window.addEventListener("session-expired", expired);
    if (sessionStorage.getItem("tripledger-token"))
      api("/auth/me")
        .then((u) => live && setUser(u))
        .catch((e) => live && setError(e.message))
        .finally(() => live && setChecking(false));
    else setChecking(false);
    return () => {
      live = false;
      window.removeEventListener("session-expired", expired);
    };
  }, []);
  const notify = (message) => {
    setSuccess(message);
    setError("");
  };
  const fail = (e) => {
    setError(e.message || String(e));
    setSuccess("");
  };
  if (checking) return <div className="loading">Opening your workspace…</div>;
  if (!user)
    return (
      <Login
        onLogin={(u) => {
          setUser(u);
          setError("");
          setSuccess("");
        }}
        error={error}
        fail={fail}
      />
    );
  const admin = user.role === "ADMIN";
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <span className="brand-icon">T</span>TripLedger
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav>
          {[
            ["overview", LayoutDashboard, "Overview"],
            [
              "reports",
              ReceiptText,
              user.role === "MANAGER"
                ? "Team & my expenses"
                : "Expense reports",
            ],
            ["policies", BookOpen, "Expense policies"],
            ["account", ShieldCheck, "My account"],
            ...(admin ? [["users", Users, "People & access"]] : []),
          ].map(([id, Icon, label]) => (
            <button
              key={id}
              className={page === id ? "active" : ""}
              onClick={() => {
                setPage(id);
                setError("");
                setSuccess("");
              }}
            >
              <Icon size={19} />
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="avatar">{user.name.slice(0, 1)}</div>
          <div>
            <strong>{user.name}</strong>
            <small>{display(user.role)}</small>
          </div>
          <button
            title="Sign out"
            className="icon-button"
            onClick={async () => {
              try {
                await post("/auth/logout", {});
              } finally {
                sessionStorage.removeItem("tripledger-token");
                setUser(null);
              }
            }}
          >
            <LogOut size={18} />
          </button>
        </div>
      </aside>
      <main>
        <header>
          <span className="breadcrumb">
            Workspace{" "}
            <span>/ {page === "users" ? "People & access" : page}</span>
          </span>
          <span className="secure">
            <ShieldCheck size={15} /> Private workspace
          </span>
        </header>
        {error && (
          <div className="notice error" role="alert">
            {error}
            <button onClick={() => setError("")}>Dismiss</button>
          </div>
        )}
        {success && (
          <div className="notice success" role="status">
            {success}
            <button onClick={() => setSuccess("")}>Dismiss</button>
          </div>
        )}
        {page === "account" && <Account user={user} fail={fail} />}
        {page === "overview" && (
          <Overview
            user={user}
            onReports={() => setPage("reports")}
            fail={fail}
          />
        )}
        {page === "reports" && (
          <Reports user={user} fail={fail} notify={notify} />
        )}
        {page === "policies" && (
          <Policies admin={admin} fail={fail} notify={notify} />
        )}
        {page === "users" && admin && <People fail={fail} notify={notify} />}
        <footer>
          TripLedger · Evidence-backed reviews. Approval does not initiate
          payment.
        </footer>
      </main>
    </div>
  );
}
function Account({ user, fail }) {
  const [busy, setBusy] = useState(false);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">ACCOUNT SETTINGS</p>
          <h1>My account</h1>
          <p className="muted">
            {user.name} · {user.email}
          </p>
        </div>
      </div>
      <div className="panel">
        <h2>Change your password</h2>
        <p className="muted">
          Changing your password signs out all active sessions.
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            if (data.get("newPassword") !== data.get("confirm")) {
              fail(new Error("New passwords do not match"));
              return;
            }
            setBusy(true);
            try {
              await post("/auth/password", {
                currentPassword: data.get("currentPassword"),
                newPassword: data.get("newPassword"),
              });
              sessionStorage.removeItem("tripledger-token");
              window.dispatchEvent(new Event("session-expired"));
            } catch (e) {
              fail(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Current password">
            <input
              type="password"
              name="currentPassword"
              required
              autoComplete="current-password"
            />
          </Field>
          <Field label="New password (12–72 characters)">
            <input
              type="password"
              name="newPassword"
              minLength={12}
              maxLength={72}
              required
              autoComplete="new-password"
            />
          </Field>
          <Field label="Confirm new password">
            <input
              type="password"
              name="confirm"
              required
              autoComplete="new-password"
            />
          </Field>
          <button className="primary" disabled={busy}>
            Change password & sign out
          </button>
        </form>
      </div>
    </>
  );
}
function Login({ onLogin, error, fail }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <section className="login-story">
        <div className="brand">
          <span className="brand-icon">T</span>TripLedger
        </div>
        <div>
          <p className="eyebrow">LESS PAPERWORK. MORE CLARITY.</p>
          <h1>
            Every expense.
            <br />A clearer picture.
          </h1>
          <p>
            Submit receipts, understand policy, and keep every decision in one
            place.
          </p>
          <div className="story-card">
            <ShieldCheck />
            <span>
              AI-assisted checks.
              <br />
              <strong>People make the final decision.</strong>
            </span>
          </div>
        </div>
        <small>YOUR TEAM’S EXPENSE WORKSPACE</small>
      </section>
      <section className="login-form">
        <div>
          <p className="eyebrow">WELCOME BACK</p>
          <h2>Sign in to your workspace</h2>
          <p className="muted">
            Use the account provided by your administrator.
          </p>
          {error && (
            <p role="alert" className="notice error">
              {error}
            </p>
          )}
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              const form = new FormData(e.currentTarget);
              try {
                const result = await post("/auth/login", {
                  email: form.get("email"),
                  password: form.get("password"),
                });
                sessionStorage.setItem("tripledger-token", result.token);
                onLogin(result.user);
              } catch (e) {
                fail(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Email address">
              <input
                name="email"
                type="email"
                autoComplete="username"
                required
                placeholder="you@company.com"
              />
            </Field>
            <Field label="Password">
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </Field>
            <button className="primary wide" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
              <ArrowUpRight size={18} />
            </button>
          </form>
          <p className="fine">
            Need access? Ask your administrator to create an account and assign
            your manager.
          </p>
        </div>
      </section>
    </div>
  );
}
function Overview({ user, onReports, fail }) {
  const [reports, setReports] = useState([]);
  useEffect(() => {
    api("/reports").then(setReports).catch(fail);
  }, []);
  const count = (status) =>
    reports.filter((r) => status.includes(r.status)).length;
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR WORKSPACE AT A GLANCE</p>
          <h1>Good to see you, {user.name.split(" ")[0]}.</h1>
          <p className="muted">
            A clear view of expenses, reviews, and next steps.
          </p>
        </div>
        <button className="primary" onClick={onReports}>
          Open reports <ArrowUpRight size={18} />
        </button>
      </div>
      <div className="stats">
        {[
          ["Total reports", reports.length, ReceiptText],
          ["In review", count(["SUBMITTED", "AWAITING_REVIEW"]), Clock3],
          ["Needs clarification", count(["CLARIFICATION"]), RefreshCw],
          ["Approved", count(["APPROVED"]), CheckCircle2],
        ].map(([label, n, Icon]) => (
          <div className="stat" key={label}>
            <div>
              <span>{label}</span>
              <Icon size={20} />
            </div>
            <strong>{n}</strong>
          </div>
        ))}
      </div>
      <div className="panel">
        <div className="section-heading">
          <h2>Recent activity</h2>
          <button className="text-button" onClick={onReports}>
            View all →
          </button>
        </div>
        {!reports.length ? (
          <Empty text="Create your first report, or wait for your team to submit expenses." />
        ) : (
          <ReportTable reports={reports.slice(0, 6)} onSelect={onReports} />
        )}
      </div>
      <div className="info-grid">
        <div className="panel">
          <p className="eyebrow">HOW IT WORKS</p>
          <h3>From receipt to decision</h3>
          <p className="muted">
            Save a draft, attach receipts, and submit. AI gathers policy
            evidence and checks amounts. Your manager reviews the recommendation
            and records the final decision.
          </p>
        </div>
        <div className="panel tint">
          <ShieldCheck />
          <h3>Your evidence stays connected.</h3>
          <p className="muted">
            Each submission keeps its policy version, review results, and
            decision history. Clarifications create a new submitted revision.
          </p>
        </div>
      </div>
    </>
  );
}
function ReportTable({ reports, onSelect }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Report</th>
            <th>Employee</th>
            <th>Status</th>
            <th>AI review</th>
            <th>Updated</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {reports.map((r) => (
            <tr key={r.id}>
              <td>
                <button className="table-link" onClick={() => onSelect(r.id)}>
                  {r.title}
                </button>
                <small>
                  {r.payload.destination} · {r.payload.baseCurrency}
                </small>
              </td>
              <td>{r.employee_name}</td>
              <td>
                <Badge value={r.status} />
              </td>
              <td>
                <Badge value={r.ai_status} />
              </td>
              <td>{date(r.updated_at)}</td>
              <td>
                <button
                  className="icon-button"
                  aria-label={`Open ${r.title}`}
                  onClick={() => onSelect(r.id)}
                >
                  <ArrowUpRight size={17} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Reports({ user, fail, notify }) {
  const [reports, setReports] = useState([]),
    [selected, setSelected] = useState(null),
    [creating, setCreating] = useState(false),
    [detail, setDetail] = useState(null),
    [filter, setFilter] = useState("ALL"),
    [loading, setLoading] = useState(false);
  const refresh = async () => {
    try {
      setReports(await api("/reports"));
      if (selected) setDetail(await api("/reports/" + selected));
    } catch (e) {
      fail(e);
    }
  };
  useEffect(() => {
    refresh();
  }, [selected]);
  useEffect(() => {
    if (!detail || !["SUBMITTED"].includes(detail.status)) return;
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [detail?.status, selected]);
  const select = (id) => {
    setDetail(null);
    setSelected(id);
    setCreating(false);
  };
  const saved = async (r) => {
    setCreating(false);
    setSelected(r.id);
    setDetail(await api("/reports/" + r.id));
    setReports(await api("/reports"));
  };
  if (creating)
    return (
      <>
        <button className="back" onClick={() => setCreating(false)}>
          <ArrowLeft size={16} /> Back to reports
        </button>
        <ReportEditor
          user={user}
          report={null}
          saved={saved}
          fail={fail}
          notify={notify}
        />
      </>
    );
  if (selected)
    return (
      <>
        <button
          className="back"
          onClick={() => {
            setSelected(null);
            setDetail(null);
          }}
        >
          <ArrowLeft size={16} /> Back to reports
        </button>
        {detail ? (
          <ReportDetail
            report={detail}
            user={user}
            saved={saved}
            refresh={refresh}
            fail={fail}
            notify={notify}
          />
        ) : (
          <div className="panel">Loading report…</div>
        )}
      </>
    );
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">EXPENSE MANAGEMENT</p>
          <h1>
            {user.role === "MANAGER" ? "Team & my expenses" : "Expense reports"}
          </h1>
          <p className="muted">Track every report from draft to decision.</p>
        </div>
        {user.role !== "ADMIN" && (
          <button className="primary" onClick={() => setCreating(true)}>
            <Plus size={18} /> New report
          </button>
        )}
      </div>
      <div className="panel">
        <div className="section-heading">
          <div className="filters">
            <select
              aria-label="Filter reports"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              {[
                "ALL",
                "DRAFT",
                "SUBMITTED",
                "AWAITING_REVIEW",
                "CLARIFICATION",
                "APPROVED",
                "REJECTED",
              ].map((s) => (
                <option key={s} value={s}>
                  {s === "ALL" ? "All reports" : display(s)}
                </option>
              ))}
            </select>
          </div>
          <button
            disabled={loading}
            className="secondary"
            onClick={async () => {
              setLoading(true);
              await refresh();
              setLoading(false);
            }}
          >
            <RefreshCw size={16} /> Refresh
          </button>
        </div>
        {reports.filter((r) => filter === "ALL" || r.status === filter)
          .length ? (
          <ReportTable
            reports={reports.filter(
              (r) => filter === "ALL" || r.status === filter,
            )}
            onSelect={select}
          />
        ) : (
          <Empty text="No reports match this view." />
        )}
      </div>
    </>
  );
}
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const newLine = () => ({
  lineId: crypto.randomUUID().slice(0, 8),
  date: today(),
  category: "taxi",
  merchant: "",
  amount: "",
  currency: "EUR",
  description: "",
  receiptId: null,
  hotelNights: null,
  attendeeCount: null,
  clientDinner: null,
  alcoholAmount: null,
});
function ReportEditor({ user, report, saved, fail, notify }) {
  const [draft, setDraft] = useState(
      report?.payload || {
        title: "",
        purpose: "",
        destination: "",
        startDate: today(),
        endDate: today(),
        baseCurrency: "EUR",
        lines: [newLine()],
      },
    ),
    [busy, setBusy] = useState(false),
    [submit, setSubmit] = useState(false);
  const field = (key, value) => setDraft((d) => ({ ...d, [key]: value }));
  const line = (i, key, value) =>
    setDraft((d) => ({
      ...d,
      lines: d.lines.map((l, n) => (i === n ? { ...l, [key]: value } : l)),
    }));
  useEffect(() => {
    if (report) setDraft(report.payload);
  }, [report?.id, report?.row_version]);
  const persist = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const data = {
        ...draft,
        rowVersion: report?.row_version || 0,
        lines: draft.lines.map((l) => ({
          ...l,
          amount: String(l.amount),
          hotelNights: l.hotelNights ? Number(l.hotelNights) : null,
          attendeeCount: l.attendeeCount ? Number(l.attendeeCount) : null,
          alcoholAmount: l.alcoholAmount === "" ? null : l.alcoholAmount,
        })),
      };
      let r = report
        ? await api("/reports/" + report.id, {
            method: "PUT",
            body: JSON.stringify(data),
          })
        : await post("/reports", data);
      if (submit) {
        try {
          r = await post("/reports/" + r.id + "/submit", {
            rowVersion: r.row_version,
          });
        } catch (e) {
          await saved(r);
          throw e;
        }
      }
      await saved(r);
      notify(
        submit
          ? "Report submitted. AI review will run in the background."
          : "Draft saved. You can now upload receipts.",
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {report ? "EDIT REPORT" : "NEW EXPENSE REPORT"}
          </p>
          <h1>{report?.title || "Tell us about your trip."}</h1>
          <p className="muted">
            Signed in as {user.name}. Your employee identity is added
            automatically.
          </p>
        </div>
        <Badge value={report?.status || "DRAFT"} />
      </div>
      <form onSubmit={persist}>
        <fieldset disabled={busy} className="form-reset">
          <div className="panel">
            <h2>Trip details</h2>
            <div className="form-grid">
              <Field label="Report title">
                <input
                  required
                  maxLength={160}
                  value={draft.title}
                  onChange={(e) => field("title", e.target.value)}
                  placeholder="Client visit to Mumbai"
                />
              </Field>
              <Field label="Destination">
                <input
                  required
                  maxLength={200}
                  value={draft.destination}
                  onChange={(e) => field("destination", e.target.value)}
                />
              </Field>
              <Field label="Start date">
                <input
                  required
                  type="date"
                  value={draft.startDate}
                  onChange={(e) => field("startDate", e.target.value)}
                />
              </Field>
              <Field label="End date">
                <input
                  required
                  min={draft.startDate}
                  type="date"
                  value={draft.endDate}
                  onChange={(e) => field("endDate", e.target.value)}
                />
              </Field>
              <Field label="Reimbursement currency">
                <input
                  required
                  pattern="[A-Z]{3}"
                  maxLength={3}
                  value={draft.baseCurrency}
                  onChange={(e) =>
                    field("baseCurrency", e.target.value.toUpperCase())
                  }
                />
              </Field>
              <Field label="Business purpose">
                <input
                  required
                  maxLength={2000}
                  value={draft.purpose}
                  onChange={(e) => field("purpose", e.target.value)}
                />
              </Field>
            </div>
          </div>
          <div className="panel">
            <div className="section-heading">
              <h2>Expenses</h2>
              <span className="muted">{draft.lines.length} items</span>
            </div>
            {draft.lines.map((l, i) => (
              <section className="expense-card" key={l.lineId}>
                <div className="section-heading">
                  <h3>Expense {i + 1}</h3>
                  <button
                    type="button"
                    className="icon-button danger"
                    aria-label={`Remove expense ${i + 1}`}
                    disabled={draft.lines.length === 1}
                    onClick={() =>
                      field(
                        "lines",
                        draft.lines.filter((_, n) => n !== i),
                      )
                    }
                  >
                    <Trash2 size={17} />
                  </button>
                </div>
                <div className="form-grid three">
                  <Field label="Date">
                    <input
                      required
                      type="date"
                      value={l.date}
                      onChange={(e) => line(i, "date", e.target.value)}
                    />
                  </Field>
                  <Field label="Category">
                    <input
                      required
                      maxLength={60}
                      list="categories"
                      value={l.category}
                      onChange={(e) =>
                        line(i, "category", e.target.value.toLowerCase())
                      }
                    />
                  </Field>
                  <Field label="Merchant">
                    <input
                      required
                      maxLength={160}
                      value={l.merchant}
                      onChange={(e) => line(i, "merchant", e.target.value)}
                    />
                  </Field>
                  <Field label="Amount">
                    <input
                      required
                      inputMode="decimal"
                      pattern="[0-9]{1,12}(\.[0-9]{1,6})?"
                      value={l.amount}
                      onChange={(e) => line(i, "amount", e.target.value)}
                      placeholder="0.00"
                    />
                  </Field>
                  <Field label="Currency">
                    <input
                      required
                      pattern="[A-Z]{3}"
                      maxLength={3}
                      value={l.currency}
                      onChange={(e) =>
                        line(i, "currency", e.target.value.toUpperCase())
                      }
                    />
                  </Field>
                  <Field label="Business reason">
                    <input
                      required
                      maxLength={2000}
                      value={l.description}
                      onChange={(e) => line(i, "description", e.target.value)}
                    />
                  </Field>
                </div>
                <details>
                  <summary>Hotel and meal details</summary>
                  <div className="form-grid">
                    <Field label="Hotel nights">
                      <input
                        type="number"
                        min="1"
                        max="365"
                        value={l.hotelNights ?? ""}
                        onChange={(e) => line(i, "hotelNights", e.target.value)}
                      />
                    </Field>
                    <Field label="Attendee count">
                      <input
                        type="number"
                        min="1"
                        max="1000"
                        value={l.attendeeCount ?? ""}
                        onChange={(e) =>
                          line(i, "attendeeCount", e.target.value)
                        }
                      />
                    </Field>
                    <Field label="Client dinner">
                      <select
                        value={
                          l.clientDinner === null ? "" : String(l.clientDinner)
                        }
                        onChange={(e) =>
                          line(
                            i,
                            "clientDinner",
                            e.target.value === ""
                              ? null
                              : e.target.value === "true",
                          )
                        }
                      >
                        <option value="">Not specified</option>
                        <option value="true">Yes</option>
                        <option value="false">No</option>
                      </select>
                    </Field>
                    <Field label="Alcohol amount (same currency)">
                      <input
                        inputMode="decimal"
                        pattern="[0-9]{1,12}(\.[0-9]{1,6})?"
                        value={l.alcoholAmount ?? ""}
                        onChange={(e) =>
                          line(i, "alcoholAmount", e.target.value)
                        }
                      />
                    </Field>
                  </div>
                </details>
                <div className="receipt-upload">
                  <Upload size={19} />
                  <div>
                    <strong>
                      {l.receiptId ? "Receipt attached" : "Attach receipt"}
                    </strong>
                    <p className="fine">
                      {report
                        ? "PNG or JPEG, up to 8 MB. Save changes after upload."
                        : "Save your draft first to enable receipt uploads."}
                    </p>
                  </div>
                  <input
                    aria-label={`Upload receipt for expense ${i + 1}`}
                    type="file"
                    accept="image/png,image/jpeg"
                    disabled={!report || busy}
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      if (file.size > 8 * 1024 * 1024) {
                        fail(new Error("Receipt must be under 8 MB"));
                        return;
                      }
                      setBusy(true);
                      try {
                        const body = new FormData();
                        body.append("file", file);
                        const receipt = await api(
                          "/reports/" + report.id + "/receipts",
                          { method: "POST", body },
                        );
                        line(i, "receiptId", receipt.id);
                        notify(
                          "Receipt uploaded. Save the draft or submit to attach it to this expense.",
                        );
                      } catch (e) {
                        fail(e);
                      } finally {
                        setBusy(false);
                        e.target.value = "";
                      }
                    }}
                  />
                </div>
              </section>
            ))}
            <button
              type="button"
              className="secondary wide dashed"
              disabled={draft.lines.length >= 50}
              onClick={() =>
                field("lines", [
                  ...draft.lines,
                  { ...newLine(), currency: draft.baseCurrency },
                ])
              }
            >
              <Plus size={17} /> Add expense
            </button>
          </div>
          <div className="action-bar">
            <p className="fine">
              Submission starts an AI review using your organization’s
              configured APIs.
            </p>
            <button
              className="secondary"
              type="submit"
              onClick={() => setSubmit(false)}
            >
              Save draft
            </button>
            <button
              className="primary"
              type="submit"
              onClick={() => setSubmit(true)}
            >
              {busy ? "Working…" : "Submit for review"}
              <ArrowUpRight size={18} />
            </button>
          </div>
        </fieldset>
      </form>
      <datalist id="categories">
        {["taxi", "hotel", "meal", "flight", "train", "parking", "other"].map(
          (c) => (
            <option key={c} value={c} />
          ),
        )}
      </datalist>
    </>
  );
}
function ReportDetail({ report: r, user, saved, refresh, fail, notify }) {
  const [busy, setBusy] = useState(false),
    [assignment, setAssignment] = useState(""),
    [managers, setManagers] = useState([]);
  const owner = r.employee_id === user.id,
    canDecide = user.role === "MANAGER" && r.manager_id === user.id && !owner;
  useEffect(() => {
    if (user.role === "ADMIN")
      api("/users")
        .then((u) =>
          setManagers(
            u.filter(
              (x) => x.role === "MANAGER" && x.active && x.id !== r.employee_id,
            ),
          ),
        )
        .catch(fail);
  }, [r.id]);
  const action = async (path, body) => {
    setBusy(true);
    try {
      await post("/reports/" + r.id + "/" + path, {
        rowVersion: r.row_version,
        ...body,
      });
      await refresh();
      notify("Report updated.");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  const editable = owner && ["DRAFT", "CLARIFICATION"].includes(r.status);
  const ai = r.ai_result;
  return (
    <>
      {r.status === "CLARIFICATION" && (
        <div className="notice warning">
          <strong>Clarification requested:</strong> {r.decision?.reason}
        </div>
      )}
      {editable ? (
        <ReportEditor
          user={user}
          report={r}
          saved={saved}
          fail={fail}
          notify={notify}
        />
      ) : (
        <>
          <div className="page-heading">
            <div>
              <p className="eyebrow">REPORT · REVISION {r.revision}</p>
              <h1>{r.title}</h1>
              <p className="muted">
                {r.employee_name} · {r.payload.destination} ·{" "}
                {r.payload.startDate} to {r.payload.endDate}
              </p>
            </div>
            <Badge value={r.status} />
          </div>
          <div className="panel">
            <div className="section-heading">
              <h2>Submitted expenses</h2>
              <button
                className="secondary"
                onClick={() => downloadJSON(r, "tripledger-report.json")}
              >
                Download report
              </button>
            </div>
            <p className="muted">{r.payload.purpose}</p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Merchant</th>
                    <th>Category / date</th>
                    <th>Amount</th>
                    <th>Purpose</th>
                    <th>Receipt</th>
                  </tr>
                </thead>
                <tbody>
                  {r.payload.lines.map((l) => (
                    <tr key={l.lineId}>
                      <td>
                        {l.merchant}
                        <small>{l.lineId}</small>
                      </td>
                      <td>
                        {l.category}
                        <small>{l.date}</small>
                      </td>
                      <td>{money(l.amount, l.currency)}</td>
                      <td>{l.description}</td>
                      <td>
                        {l.receiptId ? (
                          <button
                            className="text-button"
                            onClick={() =>
                              downloadReceipt(r.id, l.receiptId).catch(fail)
                            }
                          >
                            Download
                          </button>
                        ) : (
                          "Not attached"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
      {r.revision > 0 && (
        <div className="panel">
          <div className="section-heading">
            <h2>AI assessment</h2>
            <Badge value={r.ai_status} />
          </div>
          {!ai ? (
            <p className="muted">
              Your review is queued or processing. This page refreshes
              automatically while submitted. You may close the browser.
            </p>
          ) : (
            <>
              <p className="ai-summary">{ai.summary}</p>
              {ai.status === "COMPLETED" && (
                <>
                  <div className="stats compact">
                    {[
                      ["Claimed", ai.claimedTotal],
                      ["Recommended reimbursement", ai.reimbursableTotal],
                      ["Disallowed by caps", ai.disallowedTotal],
                    ].map(([label, value]) => (
                      <div className="stat" key={label}>
                        <span>{label}</span>
                        <strong>{money(value, ai.currency)}</strong>
                      </div>
                    ))}
                  </div>
                  <p className="fine">
                    Provisional calculations, subject to missing evidence and
                    manager review. AI does not authorize payment.
                  </p>
                  <h3>Findings</h3>
                  {ai.findings?.map((f, i) => (
                    <div className="finding" key={i}>
                      <strong>
                        {display(f.code)} {f.lineId && `· ${f.lineId}`}
                      </strong>
                      <p>{f.detail}</p>
                    </div>
                  ))}
                  <details>
                    <summary>Policy evidence and review trace</summary>
                    {ai.policyEvidence?.map((p) => (
                      <div className="evidence" key={p.chunk_id}>
                        <strong>{p.chunk_id}</strong>
                        <p>{p.content}</p>
                      </div>
                    ))}
                    <p className="fine">
                      Policy {ai.policyId} · {ai.latencyMs} ms ·{" "}
                      {ai.usage?.tokensIn} input / {ai.usage?.tokensOut} output
                      tokens
                    </p>
                    <pre>{JSON.stringify(ai.trace, null, 2)}</pre>
                  </details>
                </>
              )}
              {ai.status === "FAILED" &&
                (canDecide || user.role === "ADMIN") &&
                r.status === "AWAITING_REVIEW" && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => action("retry", {})}
                  >
                    Retry AI review
                  </button>
                )}
            </>
          )}
        </div>
      )}
      {r.decision && r.status !== "CLARIFICATION" && (
        <div className="panel">
          <h2>Recorded decision</h2>
          <p>{r.decision.reason}</p>
          {r.decision.approvedAmount != null && (
            <strong>
              {money(r.decision.approvedAmount, r.decision.currency)} approved
            </strong>
          )}
          <p className="fine">{date(r.decision.at)}</p>
        </div>
      )}
      {canDecide && r.status === "AWAITING_REVIEW" && (
        <div className="panel">
          <h2>Your decision</h2>
          <p className="muted">
            Inspect receipts and policy evidence. A reason is required for every
            decision.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              action("decision", {
                action: f.get("action"),
                reason: f.get("reason"),
                approvedAmount: f.get("approvedAmount") || null,
              });
            }}
          >
            <div className="form-grid">
              <Field label="Decision">
                <select name="action" required>
                  <option value="APPROVE">Approve</option>
                  <option value="CLARIFY">Request clarification</option>
                  <option value="REJECT">Reject</option>
                </select>
              </Field>
              <Field
                label={`Approved amount (${r.payload.baseCurrency}); required for approval`}
              >
                <input
                  name="approvedAmount"
                  inputMode="decimal"
                  pattern="[0-9]{1,14}(\.[0-9]{1,2})?"
                  defaultValue={ai?.reimbursableTotal || ""}
                />
              </Field>
            </div>
            <Field label="Reason / question for employee">
              <textarea required name="reason" maxLength={4000} rows={3} />
            </Field>
            <button className="primary" disabled={busy}>
              Record decision
            </button>
          </form>
        </div>
      )}
      {user.role === "ADMIN" &&
        !["APPROVED", "REJECTED"].includes(r.status) && (
          <div className="panel">
            <h2>Assign reviewer</h2>
            <div className="inline">
              <select
                aria-label="Assigned manager"
                value={assignment}
                onChange={(e) => setAssignment(e.target.value)}
              >
                <option value="">Select a manager</option>
                {managers.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
              <button
                className="secondary"
                disabled={!assignment || busy}
                onClick={() => action("assign", { managerId: assignment })}
              >
                Assign
              </button>
            </div>
          </div>
        )}
      <div className="panel">
        <h2>Report history</h2>
        <div className="timeline">
          {r.audit?.map((a) => (
            <div key={a.id}>
              <span className="dot" />
              <div>
                <strong>{display(a.action)}</strong>
                <p>{a.note}</p>
                <small>{date(a.at)}</small>
              </div>
            </div>
          ))}
        </div>
        {r.reviews?.length > 0 && (
          <details>
            <summary>Previous AI reviews ({r.reviews.length})</summary>
            {r.reviews.map((j) => (
              <div className="history-row" key={j.id}>
                <span>
                  Revision {j.revision} · {date(j.created_at)}
                </span>
                <Badge value={j.status} />
                {j.result && (
                  <button
                    className="text-button"
                    onClick={() =>
                      downloadJSON(j.result, `review-${j.id}.json`)
                    }
                  >
                    Download
                  </button>
                )}
              </div>
            ))}
          </details>
        )}
        {r.revisions?.length > 0 && (
          <details>
            <summary>Submitted revisions ({r.revisions.length})</summary>
            {r.revisions.map((v) => (
              <div className="history-row" key={v.revision}>
                <span>
                  Revision {v.revision} · {date(v.submitted_at)}
                </span>
                <button
                  className="text-button"
                  onClick={() => downloadJSON(v, `revision-${v.revision}.json`)}
                >
                  Download snapshot
                </button>
              </div>
            ))}
          </details>
        )}
      </div>
    </>
  );
}
function People({ fail, notify }) {
  const [people, setPeople] = useState([]),
    [editing, setEditing] = useState(null),
    [show, setShow] = useState(false),
    [busy, setBusy] = useState(false),
    [audit, setAudit] = useState([]);
  const refresh = async () => {
    setPeople(await api("/users"));
    setAudit(await api("/users/audit"));
  };
  useEffect(() => {
    refresh().catch(fail);
  }, []);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">ADMINISTRATION</p>
          <h1>People & access</h1>
          <p className="muted">
            Create accounts and connect employees with their managers.
          </p>
        </div>
        <button
          className="primary"
          onClick={() => {
            setEditing(null);
            setShow(true);
          }}
        >
          <Plus size={18} /> Add person
        </button>
      </div>
      {show && (
        <div className="panel">
          <div className="section-heading">
            <h2>{editing ? "Edit account" : "New account"}</h2>
            <button className="text-button" onClick={() => setShow(false)}>
              Cancel
            </button>
          </div>
          <form
            key={editing?.id || "new"}
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              const f = new FormData(e.currentTarget);
              const data = {
                name: f.get("name"),
                email: f.get("email"),
                role: f.get("role"),
                managerId: f.get("managerId") || null,
                password: f.get("password") || null,
                active: f.get("active") === "on",
              };
              try {
                await api("/users" + (editing ? "/" + editing.id : ""), {
                  method: editing ? "PUT" : "POST",
                  body: JSON.stringify(data),
                });
                setShow(false);
                await refresh();
                notify(
                  "Account saved. Existing sessions for edited accounts are revoked.",
                );
              } catch (e) {
                fail(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            <div className="form-grid">
              <Field label="Full name">
                <input
                  name="name"
                  required
                  maxLength={100}
                  defaultValue={editing?.name || ""}
                />
              </Field>
              <Field label="Email">
                <input
                  type="email"
                  name="email"
                  required
                  defaultValue={editing?.email || ""}
                />
              </Field>
              <Field label="Role">
                <select name="role" defaultValue={editing?.role || "EMPLOYEE"}>
                  {["EMPLOYEE", "MANAGER", "ADMIN"].map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </Field>
              <Field label="Assigned manager">
                <select
                  name="managerId"
                  defaultValue={editing?.managerId || ""}
                >
                  <option value="">No manager assigned</option>
                  {people
                    .filter(
                      (p) =>
                        p.role === "MANAGER" &&
                        p.active &&
                        p.id !== editing?.id,
                    )
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </select>
              </Field>
              <Field
                label={
                  editing
                    ? "New password (leave blank to keep current)"
                    : "Initial password (12–72 characters)"
                }
              >
                <input
                  type="password"
                  name="password"
                  minLength={12}
                  maxLength={72}
                  required={!editing}
                  autoComplete="new-password"
                />
              </Field>
              <label className="checkbox">
                <input
                  type="checkbox"
                  name="active"
                  defaultChecked={editing?.active ?? true}
                />{" "}
                Account enabled
              </label>
            </div>
            <button className="primary" disabled={busy}>
              Save account
            </button>
          </form>
        </div>
      )}
      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name / email</th>
              <th>Role</th>
              <th>Manager</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.id}>
                <td>
                  {p.name}
                  <small>{p.email}</small>
                </td>
                <td>
                  <Badge value={p.role} />
                </td>
                <td>
                  {people.find((m) => m.id === p.managerId)?.name ||
                    "Unassigned"}
                </td>
                <td>{p.active ? "Enabled" : "Disabled"}</td>
                <td>
                  <button
                    className="text-button"
                    onClick={() => {
                      setEditing(p);
                      setShow(true);
                    }}
                  >
                    Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <details>
          <summary>Account audit history</summary>
          {audit.map((a) => (
            <p key={a.id} className="fine">
              {date(a.at)} · {a.action} · {a.subject_id}
            </p>
          ))}
        </details>
      </div>
    </>
  );
}
function Policies({ admin, fail, notify }) {
  const [policies, setPolicies] = useState([]),
    [show, setShow] = useState(false),
    [busy, setBusy] = useState(false),
    [rules, setRules] = useState([
      {
        category: "hotel",
        currency: "EUR",
        limit: "100",
        basis: "PER_NIGHT",
        receiptRequired: true,
      },
    ]),
    [content, setContent] = useState("");
  const refresh = () => api("/policies").then(setPolicies);
  useEffect(() => {
    refresh().catch(fail);
  }, []);
  const rule = (i, k, v) =>
    setRules((r) => r.map((x, n) => (i === n ? { ...x, [k]: v } : x)));
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">CLEAR GUIDELINES</p>
          <h1>Expense policies</h1>
          <p className="muted">
            Submitted reports keep the policy version used for their review.
          </p>
        </div>
        {admin && (
          <button className="primary" onClick={() => setShow(!show)}>
            <Plus size={18} /> New policy version
          </button>
        )}
      </div>
      {show && (
        <div className="panel">
          <h2>Create an immutable policy version</h2>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              const title = new FormData(e.currentTarget).get("title");
              try {
                await post("/policies", { title, content, rules });
                await refresh();
                setShow(false);
                notify(
                  "Policy draft created. Publish it to generate embeddings and activate it.",
                );
              } catch (e) {
                fail(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Version title">
              <input
                name="title"
                required
                maxLength={160}
                placeholder="Travel policy · October 2026"
              />
            </Field>
            <Field label="Policy text">
              <textarea
                required
                maxLength={100000}
                rows={8}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Paste the policy text employees and managers should follow."
              />
            </Field>
            <Field label="Or load a plain text policy">
              <input
                type="file"
                accept=".txt,.md,text/plain"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    if (file.size > 100000) {
                      fail(new Error("Policy text must be under 100 KB"));
                      return;
                    }
                    setContent(await file.text());
                  }
                }}
              />
            </Field>
            <h3>Deterministic expense limits</h3>
            <p className="fine">
              These structured rules calculate caps. Keep them consistent with
              the policy text. Other policy conditions need manager
              interpretation.
            </p>
            {rules.map((r, i) => (
              <div className="rule-row" key={i}>
                <Field label="Category">
                  <input
                    required
                    value={r.category}
                    onChange={(e) =>
                      rule(i, "category", e.target.value.toLowerCase())
                    }
                  />
                </Field>
                <Field label="Currency">
                  <input
                    required
                    pattern="[A-Z]{3}"
                    maxLength={3}
                    value={r.currency}
                    onChange={(e) =>
                      rule(i, "currency", e.target.value.toUpperCase())
                    }
                  />
                </Field>
                <Field label="Limit">
                  <input
                    required
                    inputMode="decimal"
                    pattern="[0-9]{1,12}(\.[0-9]{1,2})?"
                    value={r.limit}
                    onChange={(e) => rule(i, "limit", e.target.value)}
                  />
                </Field>
                <Field label="Basis">
                  <select
                    value={r.basis}
                    onChange={(e) => rule(i, "basis", e.target.value)}
                  >
                    <option value="PER_EXPENSE">Per expense</option>
                    <option value="PER_NIGHT">Per night</option>
                    <option value="PER_ATTENDEE">Per attendee</option>
                  </select>
                </Field>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={r.receiptRequired}
                    onChange={(e) =>
                      rule(i, "receiptRequired", e.target.checked)
                    }
                  />{" "}
                  Receipt required
                </label>
                <button
                  aria-label="Remove rule"
                  type="button"
                  className="icon-button danger"
                  disabled={rules.length === 1}
                  onClick={() => setRules(rules.filter((_, n) => n !== i))}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
            <div className="inline">
              <button
                type="button"
                className="secondary"
                disabled={rules.length >= 100}
                onClick={() =>
                  setRules([
                    ...rules,
                    {
                      category: "taxi",
                      currency: "EUR",
                      limit: "50",
                      basis: "PER_EXPENSE",
                      receiptRequired: true,
                    },
                  ])
                }
              >
                Add limit
              </button>
              <button className="primary" disabled={busy}>
                Save policy draft
              </button>
            </div>
          </form>
        </div>
      )}
      {!policies.length ? (
        <div className="panel">
          <Empty
            title="No policy published yet"
            text="An administrator must create and publish a policy before employees can submit reports."
          />
        </div>
      ) : (
        policies.map((p) => (
          <div className="panel" key={p.id}>
            <div className="section-heading">
              <div>
                <h2>{p.title}</h2>
                <p className="fine">Created {date(p.created_at)}</p>
              </div>
              <Badge value={p.status} />
            </div>
            <details>
              <summary>Read policy and limits</summary>
              <p className="policy-text">{p.content}</p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Limit</th>
                      <th>Basis</th>
                      <th>Receipt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.rules.map((r, i) => (
                      <tr key={i}>
                        <td>{r.category}</td>
                        <td>{money(r.limit, r.currency)}</td>
                        <td>{display(r.basis)}</td>
                        <td>{r.receiptRequired ? "Required" : "Optional"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
            {p.error && <p className="notice error">{p.error}</p>}
            {admin && p.status !== "ACTIVE" && (
              <button
                disabled={busy}
                className="secondary"
                onClick={async () => {
                  setBusy(true);
                  try {
                    await post("/policies/" + p.id + "/publish", {});
                    await refresh();
                    notify(
                      "Policy indexed and activated. New submissions will use this version.",
                    );
                  } catch (e) {
                    fail(e);
                    await refresh();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "Indexing policy…" : "Index & publish version"}
              </button>
            )}
          </div>
        ))
      )}
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
