export default function SplashScreen() {
  return (
    <div className="app-loading-screen">
      <div className="app-loading-bg" />
      <div className="app-loading-content">
        <div className="app-loading-logo">OPS</div>
        <div className="app-loading-title">OPSFlow</div>
        <div className="app-loading-bar">
          <div className="app-loading-bar-fill" />
        </div>
        <p className="app-loading-text">Loading your workspace…</p>
      </div>
    </div>
  );
}