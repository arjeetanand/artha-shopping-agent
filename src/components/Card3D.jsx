import React, { useRef, useState, useCallback } from 'react';

/**
 * Card3D — Interactive 3D Perspective Tilt with Holographic Specular Glare
 *
 * Implements modern physical card dynamics seen on top AI product sites (Linear, Stripe, Apple VisionOS):
 * - Real-time perspective rotation following mouse coordinates
 * - Moving specular light glare that glides across the glass surface
 * - Smooth spring-like return on pointer leave
 * - Respects prefers-reduced-motion and touch interactions
 */
export function Card3D({
  children,
  className = '',
  maxTilt = 7,
  scale = 1.015,
  glare = true,
  onClick,
  style = {},
  ...props
}) {
  const cardRef = useRef(null);
  const [transform, setTransform] = useState('');
  const [glareStyle, setGlareStyle] = useState({ opacity: 0, x: 50, y: 50 });

  const handlePointerMove = useCallback((e) => {
    const card = cardRef.current;
    if (!card || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const rect = card.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const centerX = rect.width / 2;
    const centerY = rect.height / 2;

    const rotX = ((y - centerY) / centerY) * -maxTilt;
    const rotY = ((x - centerX) / centerX) * maxTilt;

    setTransform(
      `perspective(1000px) rotateX(${rotX.toFixed(2)}deg) rotateY(${rotY.toFixed(2)}deg) scale3d(${scale}, ${scale}, ${scale})`
    );

    if (glare) {
      setGlareStyle({
        opacity: 0.28,
        x: (x / rect.width) * 100,
        y: (y / rect.height) * 100,
      });
    }
  }, [glare, maxTilt, scale]);

  const handlePointerLeave = useCallback(() => {
    setTransform('perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)');
    setGlareStyle((prev) => ({ ...prev, opacity: 0 }));
  }, []);

  return (
    <div
      ref={cardRef}
      className={`card-3d ${className}`}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      onClick={onClick}
      style={{
        transform,
        transition: 'transform 180ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 180ms ease',
        transformStyle: 'preserve-3d',
        position: 'relative',
        ...style,
      }}
      {...props}
    >
      {children}
      {glare && (
        <span
          className="card-3d__glare"
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: 'inherit',
            pointerEvents: 'none',
            zIndex: 10,
            opacity: glareStyle.opacity,
            transition: 'opacity 300ms ease',
            background: `radial-gradient(circle 240px at ${glareStyle.x}% ${glareStyle.y}%, rgba(255, 255, 255, 0.25) 0%, rgba(255, 255, 255, 0) 70%)`,
          }}
        />
      )}
    </div>
  );
}
