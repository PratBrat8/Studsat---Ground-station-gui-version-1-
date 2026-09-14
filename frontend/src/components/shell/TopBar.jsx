import React from 'react';

const LABELS = {
  rocket: 'Rocket',
  satellite: 'Satellite',
  replay: 'Replay',
  settings: 'Settings',
};

export default function TopBar({ tabs, activeTab, onTabChange, backendStatus }) {
  const pillClass =
    backendStatus.state === 'ok'
      ? 'backend-pill ok'
      : backendStatus.state === 'err'
        ? 'backend-pill err'
        : 'backend-pill';

  const pillText =
    backendStatus.state === 'ok'
      ? `Backend ${backendStatus.version}`
      : backendStatus.state === 'err'
        ? 'Backend offline'
        : 'Backend…';

  return (
    <header className="topbar">
      <div className="brand">
        STUDSAT <span>GS</span>
      </div>
      <nav className="tabnav" aria-label="Main">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            className={activeTab === tab ? 'active' : ''}
            onClick={() => onTabChange(tab)}
          >
            {LABELS[tab] ?? tab}
          </button>
        ))}
      </nav>
      <div className={pillClass} title={backendStatus.error || ''}>
        {pillText}
      </div>
    </header>
  );
}
