---
name: 3d-sliding-scroll-animation
description: >-
  Builds high-performance 3D sliding animations and scroll-driven perspective transforms for modern web applications.
  Trigger when creating 3D card carousels, 3D container scroll effects, horizontal sliding panels with perspective depth,
  Aceternity/Inspira-style 3D scroll animations, or CSS scroll-timeline 3D interactions.
---

# 3D Sliding Animation with Scroll

This skill provides the architectural foundation, mathematical formulas, CSS 3D rendering pipeline, and production React implementations for **3D sliding animations coupled to scroll behavior**.

---

## 1. Core Mathematical & CSS 3D Pipeline

Creating smooth 3D animations during scroll requires understanding the CSS 3D rendering context:

### The 3D Coordinate Space
* **`perspective`**: Sets the distance between the user's viewpoint and the $z=0$ plane. Lower values ($600\text{px}-800\text{px}$) create dramatic, extreme lens distortion; higher values ($1200\text{px}-2000\text{px}$) create elegant, subtle editorial depth.
* **`transform-style: preserve-3d`**: Crucial on parent containers so nested children exist in true 3D space rather than being flattened into a 2D plane.
* **`perspective-origin`**: Anchor point for the camera (usually `50% 50%` or `50% 20%` for a slightly elevated vantage point).
* **`translateZ` & `rotateX` / `rotateY`**:
  * $rotateX(\theta)$: Tilts the plane forward or backward as it scrolls into view (ideal for card entry).
  * $rotateY(\phi)$: Rotates cards around the vertical axis for horizontal sliding galleries.
  * $translateZ(\zeta)$: Pulls the active/focused card closer to the user, creating natural layering without z-index hacks.

```css
/* Container 3D Stage */
.stage-3d {
  perspective: 1200px;
  perspective-origin: 50% 50%;
  transform-style: preserve-3d;
}

/* 3D Sliding Item */
.card-3d {
  transform-style: preserve-3d;
  will-change: transform, opacity;
  backface-visibility: hidden;
  transform: 
    perspective(1200px)
    rotateX(calc(var(--scroll-progress, 0) * 15deg))
    rotateY(calc(var(--slide-offset, 0) * -12deg))
    translateZ(calc(var(--scroll-depth, 0) * 60px))
    scale(calc(1 - (1 - var(--scroll-progress, 1)) * 0.08));
  transition: transform 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}
```

---

## 2. Scroll-Driven 3D Sliding Implementations

### Pattern A: Modern Native CSS Scroll-Driven Animations (Zero JS Runtime)
For browsers supporting CSS `animation-timeline` (Chrome, Edge, modern Chromium):

```css
@supports (animation-timeline: view()) {
  .stage-3d-scroll {
    perspective: 1400px;
    perspective-origin: center top;
  }

  .scroll-3d-card {
    animation: slideAndTilt3D linear both;
    animation-timeline: view();
    animation-range: entry 0% cover 60%;
    transform-origin: center bottom;
  }

  @keyframes slideAndTilt3D {
    0% {
      opacity: 0.2;
      transform: perspective(1400px) translateY(80px) translateZ(-200px) rotateX(25deg) scale(0.9);
    }
    50% {
      opacity: 1;
      transform: perspective(1400px) translateY(0) translateZ(0) rotateX(0deg) scale(1);
    }
    100% {
      opacity: 0.8;
      transform: perspective(1400px) translateY(-40px) translateZ(-100px) rotateX(-12deg) scale(0.95);
    }
  }
}
```

---

### Pattern B: Cross-Browser 60fps/120fps React Hook (`use3dScrollSlide`)
For universal compatibility across Safari, Firefox, iOS, and Android:
Uses non-blocking `requestAnimationFrame` + `IntersectionObserver` to bind scroll percentage directly to CSS custom properties.

```jsx
import { useEffect, useRef, useState } from 'react';

/**
 * use3DScroll - Calculates smooth 0-to-1 scroll progress inside viewport
 */
export function use3DScroll({ offset = 0.2 } = {}) {
  const containerRef = useRef(null);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    let rafId = null;
    const handleScroll = () => {
      const rect = el.getBoundingClientRect();
      const windowHeight = window.innerHeight;
      
      // Calculate progress between entering bottom and reaching center
      const start = windowHeight;
      const end = windowHeight * offset;
      const current = rect.top;
      
      const raw = (start - current) / (start - end);
      const clamped = Math.min(Math.max(raw, 0), 1);
      
      // Smooth interpolation
      setProgress((prev) => prev + (clamped - prev) * 0.2);
    };

    const onScroll = () => {
      if (!rafId) {
        rafId = requestAnimationFrame(() => {
          handleScroll();
          rafId = null;
        });
      }
    };

    window.addEventListener('scroll', onScroll, { passive: true });
    handleScroll();

    return () => {
      window.removeEventListener('scroll', onScroll);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [offset]);

  return { containerRef, progress };
}
```

---

## 3. High-End 3D Component Recipes

### 1. 3D Container Scroll (Aceternity / Inspira UI Pattern)
A heroic container that tilts on an oblique 3D plane at the top of the viewport and flattens out gracefully as the user scrolls into it:

```jsx
export function ContainerScroll3D({ title, children }) {
  const { containerRef, progress } = use3DScroll({ offset: 0.3 });

  // Rotate from 20deg down to 0deg, scale from 0.94 up to 1
  const rotateX = 20 * (1 - progress);
  const scale = 0.92 + 0.08 * progress;
  const translateZ = -120 * (1 - progress);

  return (
    <div ref={containerRef} className="container-scroll-wrap" style={{ perspective: '1200px' }}>
      <div className="container-scroll-header">
        {title}
      </div>
      <div
        className="container-scroll-card"
        style={{
          transform: `perspective(1200px) rotateX(${rotateX}deg) scale(${scale}) translateZ(${translateZ}px)`,
          transformStyle: 'preserve-3d',
          transition: 'transform 0.1s linear',
        }}
      >
        {children}
      </div>
    </div>
  );
}
```

### 2. 3D Horizontal Sliding Card Carousel on Vertical Scroll
Transforms vertical scroll displacement into a 3D curved sliding carousel:

```jsx
export function Carousel3DSlide({ items }) {
  const containerRef = useRef(null);
  const [scrollIndex, setScrollIndex] = useState(0);

  return (
    <div ref={containerRef} className="carousel-3d-stage">
      <div className="carousel-3d-track">
        {items.map((item, index) => {
          const delta = index - scrollIndex;
          const rotateY = delta * -18; // 3D curve angle
          const translateX = delta * 260; // Horizontal slide distance
          const translateZ = Math.abs(delta) * -80; // Distance fading back
          const opacity = Math.max(1 - Math.abs(delta) * 0.35, 0.2);

          return (
            <div
              key={item.id || index}
              className="carousel-3d-item"
              style={{
                transform: `translateX(${translateX}px) translateZ(${translateZ}px) rotateY(${rotateY}deg)`,
                opacity,
                zIndex: 100 - Math.abs(Math.round(delta)),
              }}
            >
              {item.content}
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

---

## 4. Performance & Accessibility Rules

1. **Hardware Acceleration**: Always apply `will-change: transform` and `backface-visibility: hidden` to elements animated in 3D.
2. **Layer Separation**: Avoid applying heavy blur filters (`backdrop-filter`) directly on elements with active 3D rotations, as this forces repaints on the GPU composite tree. Keep blur on static layers and rotate clean surfaces.
3. **Respect Reduced Motion**:
   ```css
   @media (prefers-reduced-motion: reduce) {
     .card-3d, .container-scroll-card, .carousel-3d-item {
       transform: none !important;
       transition: none !important;
       animation: none !important;
     }
   }
   ```
4. **Mobile Optimization**: On touch viewports ($<768\text{px}$), reduce perspective rotation angles ($\leq 8^\circ$) and $translateZ$ depths ($\leq 40\text{px}$) to prevent horizontal clipping.
