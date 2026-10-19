/** components/auth/AutofillDecoy.jsx */

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
