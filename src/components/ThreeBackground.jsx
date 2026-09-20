import { useEffect, useRef } from 'react';
import * as THREE from 'three';

/**
 * ThreeBackground — animated particle field canvas.
 *
 * Renders a fixed, full-viewport canvas at z-index: -1 behind all content.
 * Features:
 *   - Floating particle field with subtle connecting lines between close particles
 *   - Mouse-reactive camera tilt (gentle parallax, not jarring)
 *   - AdditiveBlending for a soft neon glow on particles
 *   - Respects prefers-reduced-motion: static render only when motion is reduced
 *   - Cleans up renderer, geometry, and material on unmount
 */
export function ThreeBackground() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // ── Renderer ──────────────────────────────────────────────────────────────
    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: false,
      powerPreference: 'low-power',
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    // ── Scene & Camera ────────────────────────────────────────────────────────
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 80;

    // ── Particle Geometry ─────────────────────────────────────────────────────
    const PARTICLE_COUNT = window.innerWidth < 768 ? 280 : 520;
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const colors = new Float32Array(PARTICLE_COUNT * 3);
    const sizes = new Float32Array(PARTICLE_COUNT);

    // Color palette — cyan, violet, mint
    const palette = [
      new THREE.Color(0x63d5ff), // electric cyan
      new THREE.Color(0x8b5cf6), // vivid violet
      new THREE.Color(0x06ffa5), // neon mint
      new THREE.Color(0x3b82f6), // blue
    ];

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const i3 = i * 3;
      positions[i3]     = (Math.random() - 0.5) * 200;
      positions[i3 + 1] = (Math.random() - 0.5) * 180;
      positions[i3 + 2] = (Math.random() - 0.5) * 100;

      const color = palette[Math.floor(Math.random() * palette.length)];
      colors[i3]     = color.r;
      colors[i3 + 1] = color.g;
      colors[i3 + 2] = color.b;

      sizes[i] = Math.random() * 1.8 + 0.4;
    }

    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    particleGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    particleGeo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    const particleMat = new THREE.PointsMaterial({
      size: 0.9,
      vertexColors: true,
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });

    const particles = new THREE.Points(particleGeo, particleMat);
    scene.add(particles);

    // ── Connection Lines ──────────────────────────────────────────────────────
    // Thin lines between nearby particles — builds the "network mesh" feel
    const LINE_THRESHOLD = 28;
    const linePositions = [];
    const lineColors = [];

    const pos = particleGeo.attributes.position.array;
    const col = particleGeo.attributes.color.array;

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const ax = pos[i * 3], ay = pos[i * 3 + 1], az = pos[i * 3 + 2];
      for (let j = i + 1; j < PARTICLE_COUNT; j++) {
        const dx = ax - pos[j * 3];
        const dy = ay - pos[j * 3 + 1];
        const dz = az - pos[j * 3 + 2];
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist < LINE_THRESHOLD) {
          linePositions.push(ax, ay, az, pos[j * 3], pos[j * 3 + 1], pos[j * 3 + 2]);
          const alpha = 1 - dist / LINE_THRESHOLD;
          // Blend start/end colors, dim by distance
          lineColors.push(
            col[i * 3] * alpha, col[i * 3 + 1] * alpha, col[i * 3 + 2] * alpha,
            col[j * 3] * alpha, col[j * 3 + 1] * alpha, col[j * 3 + 2] * alpha,
          );
        }
      }
    }

    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
    lineGeo.setAttribute('color', new THREE.Float32BufferAttribute(lineColors, 3));

    const lineMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.12,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    const lines = new THREE.LineSegments(lineGeo, lineMat);
    scene.add(lines);

    // ── Mouse Parallax ────────────────────────────────────────────────────────
    const mouse = { x: 0, y: 0 };
    const targetCam = { x: 0, y: 0 };

    const onMouseMove = (e) => {
      mouse.x = (e.clientX / window.innerWidth - 0.5) * 2;
      mouse.y = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener('mousemove', onMouseMove, { passive: true });

    // ── Animation Loop ────────────────────────────────────────────────────────
    let rafId;
    let time = 0;

    const animate = () => {
      rafId = requestAnimationFrame(animate);
      time += 0.0012;

      if (!prefersReducedMotion) {
        // Slow drift of the entire particle cloud
        particles.rotation.y = time * 0.06;
        particles.rotation.x = Math.sin(time * 0.04) * 0.08;
        lines.rotation.y = particles.rotation.y;
        lines.rotation.x = particles.rotation.x;

        // Smooth camera parallax towards mouse
        targetCam.x += (mouse.x * 4 - targetCam.x) * 0.03;
        targetCam.y += (-mouse.y * 3 - targetCam.y) * 0.03;
        camera.position.x = targetCam.x;
        camera.position.y = targetCam.y;
        camera.lookAt(scene.position);

        // Gentle opacity pulse on particles
        particleMat.opacity = 0.45 + Math.sin(time * 1.2) * 0.08;
      }

      renderer.render(scene, camera);
    };

    animate();

    // ── Resize Handler ────────────────────────────────────────────────────────
    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener('resize', onResize);

    // ── Cleanup ───────────────────────────────────────────────────────────────
    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('resize', onResize);
      particleGeo.dispose();
      particleMat.dispose();
      lineGeo.dispose();
      lineMat.dispose();
      renderer.dispose();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        pointerEvents: 'none',
        width: '100%',
        height: '100%',
      }}
    />
  );
}
