/**
 * components/auth/AutofillDecoy.jsx
 * ------------------------------------
 * Chrome (and most Chromium browsers) ignore autocomplete="off" on fields
 * it recognizes as a login form and will still offer to fill saved
 * username/password into them — wrong on this app specifically because
 * one page hosts THREE unrelated login forms (staff/platform/patient
 * tabs) plus a registration form, so a saved credential for one role can
 * get autofilled into a completely different tab's fields.
 *
 * The reliable fix isn't a CSS/attribute trick on the real fields — it's
 * giving the browser's autofill heuristics a pair of decoy
 * username/password inputs to latch onto instead, positioned off-screen
 * (not display:none / visibility:hidden, which some autofill heuristics
 * skip over entirely — this uses a 1x1 clipped box, still "visible" to
 * the DOM/accessibility tree but invisible to the user) BEFORE the real
 * fields in tab order.
 *
 * Usage: render once near the top of any <form> that has a password
 * field. Nothing to configure — it's inert, never reads or submits data.
 */

export default function AutofillDecoy() {
  const hiddenStyle = {
    position: "absolute",
    width: 1,
    height: 1,
    padding: 0,
    margin: -1,
    overflow: "hidden",
    clip: "rect(0, 0, 0, 0)",
    whiteSpace: "nowrap",
    border: 0,
  };
  return (
    <div aria-hidden="true" style={hiddenStyle}>
      <input type="text" name="username" tabIndex={-1} autoComplete="username" />
      <input type="password" name="password" tabIndex={-1} autoComplete="current-password" />
    </div>
  );
}
