import { useEffect, useState } from "react";
import { auth } from "../api/endpoints";
import { Logo } from "../components/AppShell";
import { useAuth } from "./AuthContext";
import "./LoginPage.css";

const ROLE_COPY: Record<string, string> = {
  shopper: "Builds baskets",
  dietitian: "Reviews uncertain items",
  founder: "Audits every agent decision",
};

export default function LoginPage() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState<{ email: string; display_name: string; role: string }[]>([]);

  useEffect(() => {
    auth.demoAccounts().then(setDemo).catch(() => setDemo([]));
  }, []);

  async function submit(e?: React.FormEvent, as?: string) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(as ?? email, as ? "demo1234" : password);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="login-hero">
        <Logo />
        <h1>
          Say what you need.
          <br />
          Get a basket that's <em>safe</em>, in budget, and explained.
        </h1>
        <div className="docket" aria-hidden="true">
          <p className="docket-quote">“$100 for this week, two meals a day for us two. Jamie has a nut allergy.”</p>
          <div className="docket-rule" />
          <dl className="docket-lines mono">
            <div><dt>Budget</dt><dd>$100.00</dd></div>
            <div><dt>Meals</dt><dd>2/day × 7 days × 2</dd></div>
            <div><dt>Never</dt><dd>tree nuts · peanuts</dd></div>
            <div><dt>Checked by</dt><dd>4 agents + a dietitian</dd></div>
          </dl>
          <div className="docket-rule" />
          <div className="docket-total mono">
            <span>BASKET</span>
            <span className="shelf-tag"><span className="price">$61.40</span><span className="unit">$38.60 under</span></span>
          </div>
        </div>
      </section>

      <section className="login-panel">
        <form className="card stack" onSubmit={submit}>
          <h2>Sign in</h2>
          <label className="field">
            <span>Email</span>
            <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label className="field">
            <span>Password</span>
            <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          {error && <div className="notice notice-beet">{error}</div>}
          <button className="btn btn-primary" disabled={busy}>
            {busy ? <span className="spinner" /> : "Sign in"}
          </button>
        </form>

        {demo.length > 0 && (
          <div className="stack demo-accounts">
            <span className="eyebrow">Demo accounts</span>
            {demo.map((d) => (
              <button key={d.email} className="demo-account" onClick={() => submit(undefined, d.email)} disabled={busy}>
                <span>
                  <strong>{d.display_name}</strong>
                  <span className="small muted"> · {d.role}</span>
                </span>
                <span className="small muted">{ROLE_COPY[d.role]}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
