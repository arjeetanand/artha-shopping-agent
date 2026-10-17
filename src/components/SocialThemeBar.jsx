import React from 'react';
import { Icon } from './Icon';

export function SocialThemeBar({ theme, onClear, isLoading }) {
  if (isLoading) {
    return (
      <div className="social-theme-bar social-theme-bar--loading" role="status" aria-live="polite">
        <span className="spinner" />
        <span className="social-theme-bar__text">
          Inspecting Instagram & capturing visual design theme with Playwright…
        </span>
      </div>
    );
  }

  if (!theme || !theme.theme) return null;

  return (
    <aside className="social-theme-bar" aria-label="Extracted design theme">
      <div className="social-theme-bar__content">
        {theme.screenshot_preview ? (
          <img
            src={theme.screenshot_preview}
            alt="Instagram design reference"
            className="social-theme-bar__thumb"
          />
        ) : (
          <span className="social-theme-bar__icon-badge">
            <Icon name="spark" size={14} />
          </span>
        )}
        <div className="social-theme-bar__details">
          <div className="social-theme-bar__headline">
            <span className="social-theme-bar__badge">Theme detected</span>
            <strong className="social-theme-bar__title">{theme.theme}</strong>
          </div>
          <div className="social-theme-bar__tags">
            {(theme.colors || []).map((color) => (
              <span key={color} className="social-theme-bar__chip social-theme-bar__chip--color">
                <span className="color-dot" style={{ backgroundColor: color }} />
                {color}
              </span>
            ))}
            {(theme.style_tags || []).map((tag) => (
              <span key={tag} className="social-theme-bar__chip">
                #{tag}
              </span>
            ))}
          </div>
        </div>
      </div>
      {onClear ? (
        <button
          type="button"
          className="social-theme-bar__clear"
          onClick={onClear}
          aria-label="Remove social theme"
          title="Remove social theme"
        >
          <Icon name="close" size={14} />
        </button>
      ) : null}
    </aside>
  );
}

export default SocialThemeBar;
