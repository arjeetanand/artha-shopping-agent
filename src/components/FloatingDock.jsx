import React from 'react';
import { Icon } from './Icon';

export function FloatingDock({
  activeView,
  onNavigate,
  onOpenVoice,
  onNewSearch,
  planCount = 0,
  savedCount = 0,
  user = null,
  onSignIn,
}) {
  return (
    <nav className="floating-dock" aria-label="Quick Navigation Dock">
      <div className="floating-dock__body">
        {/* Left Cluster */}
        <div className="floating-dock__cluster floating-dock__cluster--left">
          <button
            type="button"
            className={`floating-dock__item ${activeView === 'discover' ? 'is-active' : ''}`}
            onClick={() => onNavigate('discover')}
            title="Discover & 7-Agent Research"
            aria-label="Discover"
          >
            <Icon name="search" size={18} />
            <span className="floating-dock__tooltip">Discover</span>
          </button>

          <button
            type="button"
            className={`floating-dock__item ${activeView === 'saved' ? 'is-active' : ''}`}
            onClick={() => onNavigate('saved')}
            title="Saved Bookmarks"
            aria-label="Saved"
          >
            <Icon name="bookmark" size={18} />
            {savedCount > 0 && <span className="floating-dock__badge">{savedCount}</span>}
            <span className="floating-dock__tooltip">Saved</span>
          </button>

          <button
            type="button"
            className={`floating-dock__item ${activeView === 'plans' ? 'is-active' : ''}`}
            onClick={() => onNavigate('plans')}
            title="My Bags & Purchase Plans"
            aria-label="My Bags"
          >
            <Icon name="shoppingBag" size={18} />
            {planCount > 0 && <span className="floating-dock__badge floating-dock__badge--accent">{planCount}</span>}
            <span className="floating-dock__tooltip">My Bags</span>
          </button>
        </div>

        {/* Center Organic Notch & Elevated Plus Action Button */}
        <div className="floating-dock__center">
          <div className="floating-dock__notch-cutout" />
          <button
            type="button"
            className="floating-dock__action-btn"
            onClick={() => {
              onNavigate('discover');
              if (onNewSearch) onNewSearch();
            }}
            title="New AI Research Brief"
            aria-label="Create new research brief"
          >
            <Icon name="plus" size={24} />
            <span className="floating-dock__action-glow" />
          </button>
        </div>

        {/* Right Cluster */}
        <div className="floating-dock__cluster floating-dock__cluster--right">
          <button
            type="button"
            className={`floating-dock__item ${activeView === 'orders' ? 'is-active' : ''}`}
            onClick={() => onNavigate('orders')}
            title="Orders & Tracking"
            aria-label="Orders"
          >
            <Icon name="truck" size={18} />
            <span className="floating-dock__tooltip">Orders</span>
          </button>

          <button
            type="button"
            className="floating-dock__item floating-dock__item--voice"
            onClick={onOpenVoice}
            title="Talk to Artha (Voice)"
            aria-label="Talk to Artha voice assistant"
          >
            <Icon name="waveform" size={18} />
            <span className="floating-dock__pulse-ring" />
            <span className="floating-dock__tooltip">Voice</span>
          </button>

          <button
            type="button"
            className={`floating-dock__item ${activeView === 'usage' ? 'is-active' : ''}`}
            onClick={() => (user ? onNavigate('usage') : onSignIn ? onSignIn() : onNavigate('usage'))}
            title={user ? `${user.name || 'Account'} (${user.email || ''})` : 'Sign in'}
            aria-label={user ? 'Account' : 'Sign in'}
          >
            {user?.picture ? (
              <img src={user.picture} alt="" className="floating-dock__avatar" />
            ) : (
              <Icon name="user" size={18} />
            )}
            <span className="floating-dock__tooltip">{user ? 'Account' : 'Sign In'}</span>
          </button>
        </div>
      </div>
    </nav>
  );
}
